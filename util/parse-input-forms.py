#!/usr/bin/env python3
#
# parse-input-forms.py v0.0.2
#
# SPDX-License-Identifier: GPL-3.0-only

import argparse
import os
import sys
import xml.etree.ElementTree as ET
from datetime import timedelta

import requests
import requests_cache
from colorama import Fore


def getFieldDescription(schema: str, element: str, qualifier: str) -> str:
    """Retrieve metadata field descriptions from the DSpace REST API.

    Use this in favor of the getFieldDescriptionBuggy() method for now.
    """

    # enable transparent request cache with thirty day expiry
    expire_after = timedelta(days=30)
    # cache HTTP 200 responses
    requests_cache.install_cache("requests-cache", expire_after=expire_after)

    # prune old cache entries
    requests_cache.remove_expired_responses()

    if args.debug:
        print(f"> Looking up description")

    url = f"{args.rest_base_url}/registries/schema/{schema}"
    request_headers = {"user-agent": "curl", "Accept": "application/json"}
    response = requests.get(url, headers=request_headers)

    if response.from_cache and args.debug:
        sys.stdout.write(Fore.YELLOW + ">> Request in cache.\n" + Fore.RESET)

    # Schema exists in the registry (it should if it's in our input form!)
    if response.status_code == 200:
        if qualifier:
            # List comprehension to iterate over metadata fields looking for one
            # matching the one we want, and extracting the description.
            description = [
                field["description"]
                for field in response.json()["metadataFields"]
                if field["name"] == f"{schema}.{element}.{qualifier}"
            ]
        else:
            description = [
                field["description"]
                for field in response.json()["metadataFields"]
                if field["name"] == f"{schema}.{element}"
            ]

    # The list comprehension above yields a list, for example: ['ISBN'], so we
    # need to get the first element and return that.
    return description[0]


def parseInputForm(inputForm):
    # Get all fields on page 1 of the default DSpace submission form
    submissionFormFields = inputForm.findall(
        "./form-definitions/form[@name='traditional']/page[@number='1']/field"
    )

    for field in submissionFormFields:
        schema = field.find("./dc-schema").text
        element = field.find("./dc-element").text

        # Not all fields have qualifiers so we need to catch the AttributeError
        try:
            qualifier = field.find("./dc-qualifier").text
        except AttributeError:
            qualifier = False

        if qualifier:
            metadataField = f"{schema}.{element}.{qualifier}"
            metadataFieldSlug = f"{schema}-{element}-{qualifier}"
        else:
            metadataField = f"{schema}.{element}"
            metadataFieldSlug = f"{schema}-{element}"

        if args.debug:
            print(f"Processing {metadataField}")

        # Create output directory for term
        outputDirectory = f"content/terms/{metadataFieldSlug}"
        os.makedirs(outputDirectory, mode=0o755, exist_ok=True)

        repeatable = field.find("./repeatable").text
        title = field.find("./label").text

        # Check if this field uses an external controlled vocabulary
        try:
            vocabulary = field.find("./vocabulary").text
        except AttributeError:
            vocabulary = False

        if vocabulary and args.debug:
            print(f"> Found controlled vocabulary: {vocabulary}")

        # Not using this yet, but could eventually say that the field is free
        # text if input type is onebox, or controlled if value is dropdown.
        inputType = field.find("./input-type").text

        # If this field uses DSpace value pairs it will have an attribute named
        # "value-pairs-name".
        valuePairs = field.find("./input-type[@value-pairs-name]")
        # If value-pairs-name is present we can then get the name of the value
        # pairs being used for this field.
        if valuePairs is not None:
            # find and findall only implement a subset of XPath so we can't use
            # field.find("./input-type/@value-pairs-name"). Use attrib...
            #
            # See: https://stackoverflow.com/a/6126846
            valuePairsName = valuePairs.attrib["value-pairs-name"]

            exportValuePairs(root, valuePairsName, metadataFieldSlug)

        # Try to get the metadata field's description from the REST API
        description = getFieldDescription(schema, element, qualifier)
        # We can theoretically fall back to the "hint" in the input-forms.xml,
        # but they are really meant for editors, not developers.
        if description == "":
            try:
                description = field.find("./hint").text
            except AttributeError:
                description = False

        if field.find("./required").text:
            required = True
        else:
            required = False

        if description:
            print(f"> {metadataField}, required: {required}, description: {description}")
        else:
            print(f"> {metadataField}, required: {required}")


def exportValuePairs(inputFormsXmlRoot, valuePairsName: str, metadataFieldSlug: str):
    if args.debug:
        print(f"> Exporting value pairs: {valuePairsName}")

    with open(f'content/terms/{metadataFieldSlug}/vocabulary.txt', 'w') as f:
        # Write value pairs to vocabulary.txt
        for value in root.findall(f'.//value-pairs[@value-pairs-name="{valuePairsName}"]/pair/stored-value'):
            f.write(f'{value.text}\n')


parser = argparse.ArgumentParser(
    description="Parse a DSpace input-forms.xml file to produce documentation about submission requirements."
)
parser.add_argument(
    "-d",
    "--debug",
    help="Print debug messages.",
    action="store_true",
)
parser.add_argument(
    "-i",
    "--input-forms",
    help="Path to DSpace submission form (input-forms.xml).",
    required=True,
    type=argparse.FileType("r"),
)
parser.add_argument(
    "-r",
    "--rest-base-url",
    help="DSpace REST API base URL.",
    required=False,
    default="https://cgspace.cgiar.org/rest",
)
args = parser.parse_args()

if args.debug:
    print(f"Opening {args.input_forms.name}")

tree = ET.parse(args.input_forms)
root = tree.getroot()
parseInputForm(root)
