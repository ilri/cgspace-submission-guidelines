#!/usr/bin/env python3
#
# parse-input-forms.py v0.2.6
#
# SPDX-License-Identifier: GPL-3.0-only

import argparse
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import timedelta
from shutil import rmtree

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

        if vocabulary:
            exportControlledVocabularies(vocabulary, metadataFieldSlug)

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
        if description is None or description == "":
            try:
                description = field.find("./hint").text
            except AttributeError:
                description = ""
        else:
            # Delete some unneeded comments from the metadata description. I do
            # this here as a bit of a hack, because I want to include some link
            # to a vocab in the metadata registry, but I don't want them on the
            # documentation page.
            description = re.sub(r"\sSee.*?\.txt$", "", description)

        if field.find("./required").text:
            required = True
        else:
            required = False

        # Create an empty list with lines we'll write to the term's index.md in
        # TOML frontmatter format for Hugo.
        indexLines = []
        indexLines.append("---\n")
        indexLines.append(f"title: '{title}'\n")
        indexLines.append(f"field: '{metadataField}'\n")
        indexLines.append(f"slug: '{metadataFieldSlug}'\n")
        if description != title:
            indexLines.append(f"description: '{description}'\n")
        indexLines.append(f"required: {required}\n")
        if vocabulary or valuePairs is not None:
            indexLines.append(f"vocabulary: '{metadataFieldSlug}.txt'\n")
        # TODO: use some real date...?
        indexLines.append(f"date: '2019-05-04T00:00:00+00:00'\n")
        indexLines.append("---")

        with open(f"content/terms/{metadataFieldSlug}/index.md", "w") as f:
            f.writelines(indexLines)


def exportValuePairs(inputFormsXmlRoot, valuePairsName: str, metadataFieldSlug: str):
    if args.debug:
        print(f"> Exporting value pairs: {valuePairsName}")

    with open(f"content/terms/{metadataFieldSlug}/{metadataFieldSlug}.txt", "w") as f:
        # Write value pairs to a text file
        for value in root.findall(
            f'.//value-pairs[@value-pairs-name="{valuePairsName}"]/pair/stored-value'
        ):
            if value.text is not None:
                f.write(f"{value.text}\n")


def exportControlledVocabularies(vocabulary: str, metadataFieldSlug: str):
    if args.debug:
        print(f"> Exporting controlled vocabulary: {vocabulary}")

    # Open the controlled vocabulary file and read all node labels
    controlledVocabularyTree = ET.parse(
        f"{args.controlled_vocab_basedir}/{vocabulary}.xml"
    )
    controlledVocabularyRoot = controlledVocabularyTree.getroot()

    # Create an empty list where we'll add all the controlled vocabulary labels
    controlledVocabularyLines = []
    for value in controlledVocabularyRoot.findall(".//isComposedBy/node"):
        controlledVocabularyLines.append(f'{value.attrib["label"]}\n')

    with open(f"content/terms/{metadataFieldSlug}/{metadataFieldSlug}.txt", "w") as f:
        f.writelines(controlledVocabularyLines)


parser = argparse.ArgumentParser(
    description="Parse a DSpace input-forms.xml file to produce documentation about submission requirements."
)
parser.add_argument(
    "-c",
    "--controlled-vocab-basedir",
    help="Path to DSpace 'controlled-vocabularies' directory.",
    required=True,
)
parser.add_argument(
    "--clean",
    help="Clean output directory before building.",
    action="store_true",
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

if args.clean:
    if args.debug:
        print(f"Cleaning terms output directory")

    rmtree("content/terms", ignore_errors=True)

if args.debug:
    print(f"Creating terms output directory")
# Make sure content directory exists. This is where we will deposit all the term
# metadata and controlled vocabularies for Hugo to process.
os.makedirs("content/terms", mode=0o755, exist_ok=True)

if args.debug:
    print(f"Opening {args.input_forms.name}")

tree = ET.parse(args.input_forms)
root = tree.getroot()
parseInputForm(root)
