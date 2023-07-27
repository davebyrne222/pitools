from rich.console import Console
from rich.progress import Progress, BarColumn, TimeRemainingColumn

from .jira_api import Jira

console = Console(record=True)


def check_valid_user(jiraConf):
    jiraInst = Jira(url=jiraConf.get("url"))

    try:
        res = jiraInst.myself()

    except Exception as ex:
        console.log("There was a problem with Jira. Please see trace. Exiting", style="red")
        raise ex

    validUser = res.status_code == 200

    if not validUser:
        console.log(f"Jira returned {res.status_code} when checking user credentials", style="red")

    return validUser


def run_jira_jql(jiraConf, jql, expand=None):
    progressParams = ("[progress.description]{task.description}",
                      BarColumn(),
                      "[progress.percentage]{task.percentage:>3.0f}%",
                      "({task.completed} / {task.total})",
                      TimeRemainingColumn()
                      )

    # instantiate jira object
    jiraInst = Jira(url=jiraConf.get("url"))

    with Progress(*progressParams) as progress:
        # create task for progress bar
        task1 = progress.add_task("Retrieving Issues", start=False, total=0)

        # get results
        res = jiraInst.jql(jql, expand=expand)
        issues = res.get("issues")
        nIssues = len(issues) if issues else 0

        # Update progress bar
        total = res.get("total")
        progress.update(task1, total=total, completed=nIssues)
        progress.start_task(task1)

        # if more results than returned, paginate
        while nIssues < total:
            issues.extend(jiraInst.jql(jql, startAt=len(issues), expand=expand).get("issues", []))
            progress.update(task1, completed=len(issues))

        progress.update(task1, completed=total)

    return issues
