import os
from dataclasses import dataclass, field

from rich.console import Console

from utils.issue_parsing import extract_issue_info
from utils.jira_jql import run_jira_jql


@dataclass
class DataContainer:
    """Class for storing required data"""

    jiraConf: dict = field(default_factory=dict)
    piReportConf: dict = field(default_factory=dict)
    rawIssues: list = field(default_factory=list)
    issues: list = field(default_factory=list)
    issueFile: str = str()
    metrics: dict = field(default_factory=lambda: {
        "epics"           : dict(),
        "loadByDiscipline": dict(),
        "loadByAssignee"  : dict()}
                          )
    outputPath: str = str()
    outputDir: str = str()


dc = DataContainer()
console = Console()


def _get_issues():
    jql = ('"Team Name" = Crewmates'
           + ' AND issuetype in (Story, Defect)'
           + ' AND resolved is not EMPTY'
           + ' AND status != Canceled'
           + f' AND Sprint in ({",".join(dc.piReportConf.get("iterations"))})'
           + ' ORDER BY resolved DESC'
           )

    # jql = "key = TPRT-21099"
    issues = run_jira_jql(dc.jiraConf, jql, expand="changelog")

    console.log(f"Parsing issues...")

    for issue in issues:
        info = extract_issue_info(dc.jiraConf, issue)

        ul = [0, 0.5, 1, 1.5, 2.5, 4, 6.5, 10, 20, 50]
        es = [1, 1, 2, 3, 5, 8, 13, 20, 40, 100]

        newEstimate = [n for n, i in enumerate(ul) if i <= info["cycleTime"]][-1]

        info = info | {"newEstimate": es[newEstimate]}

        dc.rawIssues.append(info)


def _write_to_file(data):
    header = list(data[0].keys())

    with open(dc.outputPath, "w+") as fo:
        fo.write("\t".join(header) + "\n")

        for issue in data:
            row = ""

            for key in header:
                item = issue[key]
                if not isinstance(item, list):
                    row += str(item) + "\t"
                else:
                    row += ",".join(item) + "\t"

            row += "\n"
            fo.write(row)


def _create_output_dir():
    # If folder doesn't exist, then create it.
    if not os.path.isdir(dc.outputDir):
        os.makedirs(dc.outputDir)

        console.log(f"Directory created: {dc.outputDir}")


def get_story_stats(jiraConf, piReportConf):
    dc.jiraConf = jiraConf
    dc.piReportConf = piReportConf
    dc.outputDir = dc.piReportConf.get("statsOutputDir")
    dc.outputFile = dc.piReportConf.get("statsFileName") + ".tsv"
    dc.outputPath = os.path.join(dc.outputDir, dc.outputFile)

    _create_output_dir()

    _get_issues()

    console.log(f"Creating file...")

    _write_to_file(dc.rawIssues)

    console.log(f"File written to {dc.outputPath}")

    # TODO: box plot time in each status
    # TODO: Remap SP to true SP

    # TODO: time in status hist: overlay all status on same plot?
    # TODO: time to complete vs. story point estimate scatter w/fit
    # TODO: cyle time / lead time?
    # TODO: Rollover
