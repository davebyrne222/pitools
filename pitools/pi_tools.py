import argparse
import json
import os
import sys
from dataclasses import dataclass, field

import jmespath as jp
from rich.console import Console

from pi_overview import get_pi_overview
from story_stats import get_story_stats
from utils.jira_jql import check_valid_user


@dataclass
class DataContainer:
    """Class for storing required data"""

    jiraUrl: str = str()
    config: dict = field(default_factory=dict)
    jiraConf: dict = field(default_factory=dict)
    args: type[argparse.Namespace] = argparse.Namespace


console = Console(record=True)


def get_args():
    """Gets arguments and flags from command line."""
    parser = argparse.ArgumentParser(description='Program to review iteration workload & PI feature roadmap')

    subparsers = parser.add_subparsers(dest="cmd")

    # PI Overview
    subparser_pi = subparsers.add_parser(
            'overview',
            help='Display PI Overview')

    subparser_pi.add_argument(
            '-a', '--assignee', action='store_true',
            help='Include jira assignees breakdown in PI Overview')

    subparser_pi.add_argument(
            '-w', '--warnings', action='store_true',
            help='Display table of issues with warnings')

    subparser_pi.add_argument(
            '--no-logs', action='store_true',
            help='Prevent log file output of the PI overview in the logs folder')

    # Summary stats
    subparsers.add_parser(
            'stats',
            help='Produce summary statistic report for stories')

    args = parser.parse_args()

    if len(sys.argv) == 1:
        parser.print_help()

    dc.args = args


def get_config():
    base_dir = os.path.dirname(__file__)
    file_path = os.path.join(base_dir, '../config.json')

    with open(file_path, "r") as fi:
        dc.config = json.load(fi)

    dc.jiraConf = jp.search("jira", dc.config)


def main():
    # Check user credentials are valid
    if not check_valid_user(dc.jiraConf):
        return

    if dc.args.cmd == "overview":
        get_pi_overview(
            dc.jiraConf,
            dc.config,
            showAssignee=dc.args.assignee,
            showWarnings=dc.args.warnings,
            outputLog=not dc.args.no_logs
        )

    if dc.args.cmd == "stats":
        get_story_stats(dc.jiraConf, dc.config)


if __name__ == "__main__":

    # instantiate datacontainer dataclass
    dc = DataContainer()

    # get config params
    get_config()

    # Check if running via cmd or from pyinstaller bundle and get/set args
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        dc.showPiOverview = True
    else:
        # Get command line args
        get_args()

    main()
