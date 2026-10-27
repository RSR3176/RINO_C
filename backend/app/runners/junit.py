from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from app.runners.base import ParsedTestCase


def parse_junit_xml(path: str | Path) -> list[ParsedTestCase]:
    """Parse a JUnit XML file into structured test cases.

    Supports both <testsuite> and <testsuites> roots, including nested suites.
    """
    root = ET.parse(path).getroot()
    results: list[ParsedTestCase] = []

    def handle_suite(suite: ET.Element, parent_name: str | None = None) -> None:
        suite_name = suite.attrib.get("name") or parent_name
        for child in suite:
            tag = _local(child.tag)
            if tag == "testsuite":
                handle_suite(child, suite_name)
            elif tag == "testcase":
                results.append(_case_from_element(child, suite_name))

    tag = _local(root.tag)
    if tag == "testsuites":
        for suite in root:
            if _local(suite.tag) == "testsuite":
                handle_suite(suite)
    elif tag == "testsuite":
        handle_suite(root)
    else:
        # Some emitters wrap oddly — walk all testsuites/testcases.
        for suite in root.iter():
            if _local(suite.tag) == "testsuite":
                handle_suite(suite)

    # Deduplicate if we walked nested suites twice
    seen: set[tuple[str | None, str | None, str]] = set()
    unique: list[ParsedTestCase] = []
    for case in results:
        key = (case.suite_name, case.classname, case.case_name)
        if key in seen:
            continue
        seen.add(key)
        unique.append(case)
    return unique


def _local(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def _case_from_element(el: ET.Element, suite_name: str | None) -> ParsedTestCase:
    status = "passed"
    message: str | None = None
    for child in el:
        tag = _local(child.tag)
        if tag == "failure":
            status = "failed"
            message = (child.attrib.get("message") or "") + (
                f"\n{child.text}" if child.text else ""
            )
            message = message.strip() or None
            break
        if tag == "error":
            status = "error"
            message = (child.attrib.get("message") or "") + (
                f"\n{child.text}" if child.text else ""
            )
            message = message.strip() or None
            break
        if tag == "skipped":
            status = "skipped"
            message = child.attrib.get("message")
            break

    duration = None
    if "time" in el.attrib:
        try:
            duration = float(el.attrib["time"])
        except ValueError:
            duration = None

    return ParsedTestCase(
        suite_name=suite_name,
        case_name=el.attrib.get("name") or "unnamed",
        classname=el.attrib.get("classname"),
        status=status,
        message=message,
        duration_seconds=duration,
    )
