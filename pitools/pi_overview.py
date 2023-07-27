import os
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime

import jmespath as jp
import numpy as np
from rich.console import Console
from rich.markdown import Markdown
from rich.progress import BarColumn, Progress, TimeRemainingColumn
from rich.table import Table

from utils.issue_parsing import extract_issue_info
from utils.jira_jql import run_jira_jql


@dataclass
class DataContainer:
    """Class for storing required data"""

    jiraConf: dict = field(default_factory=dict)
    capacity: dict = field(default_factory=dict)
    iterations: list = field(default_factory=list)
    progIncrement: str = str()
    defaultEpic: dict = field(default_factory=lambda: dict(iters=set(), children=dict(), status=str()))
    metrics: dict = field(default_factory=lambda: dict(epics=dict(), loadByDiscipline=dict(), loadByAssignee=dict(),
                                                       loadOverview=dict(), velocityByDiscipline=dict(),
                                                       velocityOverview=dict(), warnings=dict())
                          )
    showAssignee: bool = bool()
    writeLogs: bool = bool()
    statusColorMap: dict = field(default_factory=lambda: {
        "accepted"      : "green",
        "completed"     : "green",
        "done"          : "green",
        "implementing"  : "yellow",
        "in acceptance" : "yellow",
        "in code review": "yellow",
        "in development": "yellow",
        "in qa"         : "yellow",
        "in progress"   : "yellow"
    })


dc = DataContainer()
console = Console(record=True)


def get_pi_features():
    """Gets all features that are scheduled in the specified PI in config"""

    query = (f"project = '{dc.jiraConf.get('project')}'"
             + f" AND 'PI Number' ~ '{dc.progIncrement}'"
             + " AND 'Team Name' = Crewmates"
             + " AND issuetype = 'Epic'"
             + " AND status != Canceled"
             )
    features = run_jira_jql(dc.jiraConf, query)

    for feature in features:

        info = extract_issue_info(dc.jiraConf, feature)

        key = info.get("key")
        dc.metrics["epics"][key] = deepcopy(dc.defaultEpic) | info

        if warnings := info.get("warnings"):
            dc.metrics["warnings"][key] = {"warnings": warnings, **info}


def get_issues():
    """Gets all issues for sprints specified in config"""
    epicLinks = ",".join(list(dc.metrics.get("epics").keys()))
    sprints = ",".join(dc.iterations)
    subQuery = (f"Sprint in ({sprints})"
                + " AND 'Team Name' = Crewmates"
                + " AND issuetype not in ('Epic', 'Sub-task')"
                )

    query = (f"('Epic Link' in ({epicLinks}) OR {subQuery})"
             + " AND status != Canceled"
             )

    issues = run_jira_jql(dc.jiraConf, query)

    for issue in issues:
        info = extract_issue_info(dc.jiraConf, issue)
        dc.metrics["epics"].setdefault(info.get("epicKey"), deepcopy(dc.defaultEpic)) \
            .get("iters") \
            .add(info.get("iterNo"))
        dc.metrics["epics"][info.get("epicKey")]["children"].update({info.get("key"): info})

        if warnings := info.get("warnings"):
            dc.metrics["warnings"][info.get("key")] = {"warnings": warnings, **info}


def _extract_discipline_metrics(issue):
    spEstimate = issue.get("spEstimate")
    disciplines = issue.get("discipline")
    iteration = issue.get("iteration")
    done = issue.get("status").lower() in ("accepted", "completed", "done")
    planned = iteration != "NA"

    disciplineMap = {
        "qa/automation": issue.get("qaEstimate", 0),
        "server"       : issue.get("beEstimate", 0),
        "web"          : issue.get("feEstimate", 0),
        "na"           : spEstimate
    }

    def _update_metrics(iteration, discipline, estimate, done):
        dc.metrics["loadByDiscipline"].setdefault(
                discipline, dict()).setdefault(iteration, 0)
        dc.metrics["loadByDiscipline"][discipline][iteration] += estimate

        dc.metrics["velocityByDiscipline"].setdefault(
                discipline, dict()).setdefault(iteration, 0)

        if done:
            dc.metrics["velocityByDiscipline"][discipline][iteration] += estimate

    def _update_load_overview(discipline, done, planned, estimate):
        dc.metrics["loadOverview"].setdefault(discipline, {
            "completed": 0, "remaining": 0, "planned": 0, "unplanned": 0, "total": 0})
        dc.metrics["loadOverview"][discipline]["total"] += estimate
        dc.metrics["loadOverview"][discipline]["completed"] += estimate if done else 0
        dc.metrics["loadOverview"][discipline]["remaining"] += estimate if not done else 0
        dc.metrics["loadOverview"][discipline]["planned"] += estimate if all(
                (not done, planned)) else 0
        dc.metrics["loadOverview"][discipline]["unplanned"] += estimate if all(
                (not done, not planned)) else 0

    def _update_velocity_overview(discipline, estimate):
        dc.metrics["velocityOverview"].setdefault(discipline, {
            "completed": 0})
        dc.metrics["velocityOverview"][discipline]["completed"] += estimate

    for discipline in disciplines:
        if len(disciplines) > 1:
            estimate = disciplineMap.get(discipline.lower(), spEstimate)
        else:
            estimate = spEstimate

        _update_metrics(iteration, discipline, estimate, done)

        _update_load_overview(discipline, done, planned, estimate)

        _update_velocity_overview(discipline, estimate)


def _extract_issue_metrics(children):
    for key, child in children.items():
        assignee = child.get("assignee")
        iteration = child.get("iteration")
        spEstimate = child.get("spEstimate")

        # add individual summary
        dc.metrics["loadByAssignee"].setdefault(
                assignee, dict()).setdefault(iteration, 0)
        dc.metrics["loadByAssignee"][assignee][iteration] += spEstimate

        # add discipline summary
        _extract_discipline_metrics(child)


def get_metrics():
    """searches issues and prepares metrics

    metrics:
        epics:      key, set(iterations)
        discipline: iteration load, iteration delta
        individual: iteration load, iteration delta
    """

    # Add progress bar
    progressParams = ("[progress.description]{task.description}",
                      BarColumn(),
                      "[progress.percentage]{task.percentage:>3.0f}%",
                      "({task.completed} / {task.total})",
                      TimeRemainingColumn()
                      )

    with Progress(*progressParams) as progress:
        # create task for progress bar
        task1 = progress.add_task(
                "Processing Features/Issues", total=len(dc.metrics.get("epics")))

        for epicKey, feature in dc.metrics.get("epics").items():
            _extract_issue_metrics(feature.get("children"))
            progress.advance(task1, 1)


def get_styling(key, issue):
    """Provides a colored and formatted string for printing"""

    status = issue.get("status")
    otherTeam = "*" if issue.get("teamName") != dc.jiraConf.get("teamName") else ""
    discipline = ",".join([i[0] for i in issue.get("discipline", [""]) if i])
    disciplineFmt = f"\[{discipline}]" if discipline else ""

    if issue.get("warnings"):
        colour = "red"
    else:
        colour = dc.statusColorMap.get(status.lower(), 'white')

    return f"[{colour}]{key + otherTeam :10} {disciplineFmt} ({status})[{'/' + colour}]"


def print_epic_distribution(res):
    """Prints features metrics in readable format"""

    # add columns
    columnHeadings = ("No.", "Feature", *dc.iterations, "Unplanned")
    table = Table(*columnHeadings, show_header=True,
                  header_style="bold", min_width=100, show_lines=True)

    # add rows
    rowNo = 0
    for k, v in sorted(res.items(), key=lambda x: max(x[1].get("iters", []))):
        # TODO: fix this mess: use jmespath?
        children = {iteration: "\n".join(
                [get_styling(i, j) for i, j in v.get("children").items() if j.get("iteration") == iteration]) for
            iteration in dc.iterations}
        unplanned = "\n".join(
                [get_styling(i, j) for i, j in v.get("children").items() if j.get("iteration") not in dc.iterations])

        table.add_row(str(rowNo := rowNo + 1),
                      f"{v.get('summary')}\n{get_styling(k, v)}\n{v.get('link')}",
                      *children.values(),
                      unplanned
                      )
    footer = ("[red] Issues in red have warnings (not planned, missing items, etc.)"
              + " Run script with -w option to see warnings[/red] \n"
              + "*Story is not belonging to the current team"
              )
    console.print(table)
    console.print(footer)


def print_load_overview(res):
    """Prints discipline metrics in readable format"""

    loadTotal = sum(jp.search(f'*.total', res))
    doneTotal = sum(jp.search(f'*.completed', res))
    remainingTotal = sum(jp.search(f'*.remaining', res))
    planedTotal = sum(jp.search(f'*.planned', res))
    unplannedTotal = sum(jp.search(f'*.unplanned', res))
    capTotals = {k: sum(v) for k, v in dc.capacity.items()}
    capTotals["total"] = sum(capTotals.values())
    deltaTotal = capTotals.get("total") - loadTotal

    # Create table and add totals
    table = Table(show_header=True, header_style="bold", min_width=100)

    # columns
    table.add_column("")
    for col in ("Total", "Completed", "Remaining", "[Planned, Un-Planned]"):
        table.add_column(col, justify="right")

    # rows
    table.add_row("[b u]Totals")
    table.add_row("Capacity", str(capTotals.get("total")),
                  "-", str(capTotals.get("total")), "-")
    table.add_row("Load", str(loadTotal), str(doneTotal),
                  f"{remainingTotal}", f"[{planedTotal}, {unplannedTotal}]")
    table.add_row("Delta", str(deltaTotal), "-",
                  str(capTotals.get("total") - remainingTotal), "-")
    table.add_row(end_section=True)

    # add discipline breakdown
    for k, v in sorted(res.items(), key=lambda x: x[0]):
        delta = capTotals.get(k, 0) - v.get("total")
        table.add_row(f"[b u]{k.upper()}")
        table.add_row("Capacity", str(capTotals.get(k, "-")),
                      str(capTotals.get(k, "-")), str(capTotals.get(k, "-")), "-")
        table.add_row("Load", str(v.get("total")), str(v.get("completed")),
                      f"{v.get('remaining')}", f"[{v.get('planned')}, {v.get('unplanned')}]")
        table.add_row("Delta", str(delta), str(capTotals.get(
                k, 0) - v.get("completed")), str(capTotals.get(k, 0) - v.get("remaining")), "-")
        table.add_row()

    console.print(table)


def print_load_metrics(res):
    """Prints discipline metrics in readable format"""

    loadTotals = np.array(
            [sum(jp.search(f'*."{iter_}"', res)) for iter_ in dc.iterations], dtype='>i4')
    loadTotals = np.append(loadTotals, sum(loadTotals))

    capTotals = np.sum(
            np.array(list(dc.capacity.values()), dtype='>i4'), axis=0)
    capTotals = np.append(capTotals, sum(capTotals))

    delTotals = capTotals - loadTotals

    errStyle = "[white on red]"
    totalStyle = "bold black on white"

    # Table
    table = Table(show_header=True, header_style="bold", min_width=100)

    # columns
    table.add_column("")
    for col in dc.iterations:
        table.add_column(col, justify="right")
    table.add_column("Totals", style=totalStyle, justify="right")

    # rows
    table.add_row("[b u]Totals", style=totalStyle)
    table.add_row("Capacity", *[str(i) for i in capTotals], style=totalStyle)
    table.add_row("Load", *[str(i) for i in loadTotals], style=totalStyle)
    table.add_row("Delta", *[str(i) if i >= 0 else errStyle + str(i)
                             for i in delTotals], style=totalStyle)
    table.add_section()

    # add discipline breakdown
    for k, v in sorted(res.items(), key=lambda x: x[0]):
        load = np.array([v.get(iter_, 0)
                         for iter_ in dc.iterations], dtype='>i4')
        cap = np.array(dc.capacity.get(
                k.lower(), [0 for _ in range(len(load))]), dtype='>i4')

        load = np.append(load, sum(load))
        cap = np.append(cap, sum(cap))

        delta = cap - load

        table.add_row(f"[b u]{k.upper()}")
        table.add_row("Capacity", *[str(i) for i in cap])
        table.add_row("Load", *[str(i) for i in load])
        table.add_row(
                "Delta", *[str(i) if i >= 0 else errStyle + str(i) for i in delta], style="bold")
        table.add_row()

    console.print(table)


def print_velocity_metrics(res):
    """Prints discipline metrics in readable format"""

    doneTotals = np.array(
            [sum(jp.search(f'*."{iter_}"', res)) for iter_ in dc.iterations], dtype='>i4')
    doneTotals = np.append(doneTotals, sum(doneTotals))
    totalStyle = "bold black on white"

    # Table
    table = Table(show_header=True, header_style="bold", min_width=100)

    # columns
    table.add_column("")
    for col in dc.iterations:
        table.add_column(col, justify="right")
    table.add_column("Totals", style=totalStyle, justify="right")

    # rows
    table.add_row("[b u]Totals", style=totalStyle)
    table.add_row("Completed", *[str(i) for i in doneTotals], style=totalStyle)
    table.add_section()

    # add discipline breakdown
    for k, v in sorted(res.items(), key=lambda x: x[0]):
        load = np.array([v.get(iter_, 0) for iter_ in dc.iterations], dtype='>i4')

        load = np.append(load, sum(load))

        table.add_row(f"[b u]{k.upper()}")
        table.add_row("Completed", *[str(i) for i in load])
        table.add_row()

    console.print(table)


def print_warnings(res):
    # Table
    columnHeadings = ("Key", "Warnings", "Team", "Discipline(s)", "Iteration", "Link")

    table = Table(*columnHeadings, show_header=True,
                  header_style="bold", min_width=100, show_lines=True)

    # rows
    for k, v in sorted(res.items()):
        warnings = " - " + "\n - ".join(v.get("warnings", list()))
        discipline = ",".join(v.get("discipline"))

        table.add_row(
                v.get("key"),
                warnings,
                v.get("teamName"),
                discipline,
                v.get("iteration"),
                v.get("link")
        )

    console.print(table)


def get_pi_overview(jiraConf, reportConf, showWarnings=False, showAssignee=False, outputLog=False):
    dc.jiraConf = jiraConf
    dc.capacity = reportConf.get("capacity")
    dc.progIncrement = reportConf.get("pi")
    dc.iterations = reportConf.get("iterations")

    # get features in PI
    get_pi_features()

    # Get issues from Jira
    get_issues()

    # Extract relevant metrics
    get_metrics()

    # Print results to console
    # Feature Story Distribution
    console.print(Markdown(
            "# PI Feature Story Distribution - Overview of all features within the PI (includes stories not within the current PI)"),
            style="bold blue")
    print_epic_distribution(dc.metrics["epics"])

    # Feature Load Overview
    console.print(Markdown(
            "# Feature Load Overview (includes stories not within the current PI)"), style="bold blue")
    print_load_overview(dc.metrics["loadOverview"])

    # Assignee Load Overview
    if showAssignee:
        console.print(Markdown("# Iteration Overview By Assignee (Only includes stories assigned to current PI)"),
                      style="bold blue")
        print_load_metrics(dc.metrics["loadByAssignee"])

    # Discipline Load Overview
    console.print(Markdown(
            "# Iteration Load Overview By Discipline (Only includes stories assigned to current PI)"),
            style="bold blue")
    print_load_metrics(dc.metrics["loadByDiscipline"])

    # Discipline Velocity Overview
    console.print(Markdown(
            "# Iteration Velocity Overview By Discipline (Only includes stories assigned to current PI)"),
            style="bold blue")
    print_velocity_metrics(dc.metrics["velocityByDiscipline"])

    # Warning Overview
    if showWarnings:
        console.print(Markdown(
                "# Issues Warnings. Please double check these issues to ensure metrics are accurate"),
                style="bold blue")
        print_warnings(dc.metrics["warnings"])

    # Log to file
    if outputLog:
        timestamp = datetime.now().isoformat()
        baseDir = os.path.dirname(__file__)
        filepath = os.path.join(baseDir, f'logs/log-{timestamp}')

        console.save_html(filepath + ".html")
