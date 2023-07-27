import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

import holidays as pyholidays
import jmespath as jp
from business_duration import businessDuration as busDur
from rich.console import Console


@dataclass
class DataContainer:
    """Class for storing required data"""

    jiraConf: dict = field(default_factory=dict)
    DEFAULTTIME = datetime(1970, 1, 1, tzinfo=timezone.utc)


dc = DataContainer()
console = Console()


def _get_iteration(key, iterationStr):
    """Extracts iteration number from string"""

    iteration = str()
    num = str()
    regex_ = ["AO-(PI|IP)(\d+)-IT(\d+)", "AO-PI(\d+)-Backlog"]

    if iterationStr:
        try:
            res = re.search(regex_[0], iterationStr)
            iteration = res.group(0)
            num = float(res.group(2) + "." + res.group(3))

        except AttributeError:
            try:
                res = re.search(regex_[1], iterationStr)
                iteration = res.group(0)
                num = 1000

            except AttributeError:
                str_ = iterationStr.replace('[', '\[')
                console.log(
                        f"[WARNING] {key}: No valid iteration was found:\n{str_}\n", style="bold yellow")

    return iteration, num


def _get_discipline_from_summary(summary):
    """[DEPRECATED] Extracts discipline from summary"""
    ignored = ("spike", "enabler", {dc.jiraConf.get("teamName")})
    matches = [word.lower() for word in re.findall("\[(.*?)\]", summary)]
    matches = ",".join(filter(lambda m: m.lower() not in ignored, matches))
    return matches if matches else "N/A"


def _get_discipline(components):
    """Extracts discipline from summary"""
    targets = ("qa/automation", "server", "web", "po/pm")
    matches = [word.lower() for word in components if word.lower() in targets]
    return matches if matches else ["na"]


def _raise_unhandled(type_, key, change):
    raise ValueError(f"[ERROR] Unhandled status change ({type_}) for {key}:"
                     + f" From: {change.get('fromString')} ({change.get('from')})"
                     + f" To: {change.get('toString')} ({change.get('to')})")


def _calc_business_dur(start, end):
    return busDur(startdate=start,
                  enddate=end,
                  # starttime=time(9, 0, 0),
                  # endtime=time(17, 30, 0),
                  holidaylist=pyholidays.Ireland(),
                  unit='day'
                  )


def _get_status_timings(key, changelog):
    # TODO: replace with jmespath. Starting options:
    # items = jp.search("[*].items[] | [?field == 'status']", log)
    items = jp.search(
            "[?items[?field=='status']] | sort_by(@, &created)", changelog)

    if not items:
        return dict()

    res = {
        "started"       : dc.DEFAULTTIME,
        "updated"       : dc.DEFAULTTIME,
        "accepted"      : dc.DEFAULTTIME,
        "devDuration"   : 0,
        "codeReview"    : 0,
        "qaDuration"    : 0,
        "demoDuration"  : 0,
        "cycleTime"     : 0,
        "onHoldDuration": 0
    }

    # Workflows
    # -----------------------------
    # Story: To Do, Backlog, Itertion Ready, In Development, In Code Review, IN QA, In Acceptance, Accepted, Canceled

    statusMap = {
        "3"    : "devDuration",  #
        "10011": None,  # Accepted
        "10029": None,  # cancelled
        "10044": "qaDuration",  # in qa
        "10055": None,  # todo
        "10561": None,  # backlog
        "11963": None,  # Awaiting Internal
        "11966": "devDuration",  # In Development
        "11967": "demoDuration",  # In Acceptance
        "12161": "codeReview",  # In Code Review
        "12661": None,  # iteration ready
        "12865": None,  # Analysis Done
        "13762": None,  # Pending
        "14361": None,  # Analysis In Progress
    }

    for item in items:
        timestamp = datetime.strptime(
                item.get("created"), '%Y-%m-%dT%H:%M:%S.%f%z')
        change = jp.search("[?field=='status']", item.get("items"))[0]
        duration = _calc_business_dur(res.get('updated'), timestamp)

        codeFrom = change.get('from')
        codeTo = change.get('to')

        # To In Dev.
        if codeTo in ("11966", "3"):

            if res["started"] == dc.DEFAULTTIME:
                res["started"] = timestamp
            else:
                res["onHoldDuration"] += duration

        # accepted, Done
        elif codeTo in ("10011", "10053"):
            res["accepted"] = timestamp

        # all handled status'
        if codeFrom in statusMap:

            if metric := statusMap.get(codeFrom):
                res[metric] += duration

        # Unhandled
        else:
            _raise_unhandled("From", key, change)

        res['updated'] = timestamp

    if res["started"] > dc.DEFAULTTIME:
        res["cycleTime"] = _calc_business_dur(
                res["started"], res["accepted"])

    return res


def _get_blocked_time(changelog):
    # TODO: replace with jmespath. Starting options:
    # items = jp.search("[*].items[] | [?field == 'status']", log)
    items = jp.search(
            "[?items[?field=='Flagged']] | sort_by(@, &created)", changelog)

    res = {
        "blockedDuration": 0,
    }

    previousTime = dc.DEFAULTTIME
    for item in items:
        timestamp = datetime.strptime(
                item.get("created"), '%Y-%m-%dT%H:%M:%S.%f%z')
        change = jp.search("[?field=='Flagged']", item.get("items"))[0]
        duration = _calc_business_dur(previousTime, timestamp)

        # blocked
        if not change.get('from'):
            previousTime = timestamp

        #  unblocked
        elif change.get('fromString') == "Blocked":
            res["blockedDuration"] += duration

    return res


def _check_for_warnings(info):
    """Checks if there is anything of concern with an issue"""

    # if accepted or cancelled, doesn't matter. Skip
    if any((
            info.get("resolved"),
            info.get("issueType") == "Epic",
            (len(info.get("discipline")) == 1 and 'po/pm' in info.get("discipline")))
    ):
        return list()

    noEstimates = [info.get("beEstimate") > 0, info.get("feEstimate") > 0, info.get("qaEstimate") > 0].count(True)
    noDisciplines = len(info.get("discipline"))

    warningMap = [
        # Check if issue is not scheduled to be completed in current PI
        {
            "test"   : info.get("iterNo") == 1000,
            "warning": "Issue not scheduled in current PI"
        },
        # Check if missing team name
        {
            "test"   : info.get("teamName") != dc.jiraConf.get("teamName"),
            "warning": f"Team Name ({info.get('teamName')}) does not match the config ({dc.jiraConf.get('teamName')})"
        },
        # Check if missing epic
        {
            "test"   : info.get("epicKey") == "N/A",
            "warning": "Issue not assigned to epic"
        },
        # Check if missing discipline
        {
            "test"   : info.get("discipline")[0] == "na",
            "warning": "Issue is missing labels"
        },
        # Check if missing sp estimate
        {
            "test"   : info.get("spEstimate") == 0,
            "warning": "Issue has not been estimated"
        },
        # Check if the right number of discipline estimates are set
        {
            "test"   : noDisciplines > 1 and (noEstimates != noDisciplines),
            "warning": "Issue is missing discipline estimate"
        },
        {
            "test"   : noDisciplines == 1 and (noEstimates > 1),
            "warning": "Issue has more estimates than disciplines"
        }
    ]

    return [item.get("warning") for item in warningMap if item.get("test")]


def extract_issue_info(jiraConf, issue):
    """Returns a flattened version of info with relevant info"""

    dc.jiraConf = jiraConf

    key = jp.search("key", issue)

    tmp = {
        "key"       : key,
        "assignee"  : jp.search('fields.assignee.displayName', issue) or "NA",
        "beEstimate": jp.search("fields.customfield_20501", issue) or 0,
        "components": jp.search("fields.components[].name", issue),
        "discipline": _get_discipline(jp.search("fields.labels", issue)),
        "feEstimate": jp.search("fields.customfield_20500", issue) or 0,
        "epicKey"   : jp.search("fields.customfield_11000", issue) or "N/A",
        "issueType" : jp.search("fields.issuetype.name", issue) or "N/A",
        "labels"    : jp.search("fields.labels", issue),
        "link"      : f"{dc.jiraConf.get('url')}/browse/{key}",
        "qaEstimate": jp.search("fields.customfield_20502", issue) or 0,
        "resolution": jp.search("fields.resolution.name", issue) or "Unresolved",
        "spEstimate": jp.search("fields.customfield_10501", issue) or 0,
        "status"    : jp.search("fields.status.name", issue),
        "summary"   : jp.search("fields.summary", issue) or "N/A",
        "teamName"  : jp.search("fields.customfield_15500.value", issue) or "N/A"
    }

    # resolved
    tmp["resolved"] = any((
        tmp.get("status").lower() == "complete",
        tmp.get("resolution").lower() != "unresolved"
    ))

    # iteration
    iteration = _get_iteration(
            key, jp.search("fields.customfield_10007[-1]", issue))

    if iteration[0]:
        iter_, iterNo = iteration
    elif tmp.get("resolved"):
        iter_, iterNo = ("NA", 0)
    else:
        iter_, iterNo = ("NA", 1000)

    tmp.update({
        "iteration": iter_,
        "iterNo"   : iterNo,
    })

    # status timings
    if changelog := jp.search("changelog.histories", issue):
        tmp.update(_get_status_timings(key, changelog))
        tmp.update(_get_blocked_time(changelog))

    # warnigns
    tmp["warnings"] = _check_for_warnings(tmp)

    return tmp
