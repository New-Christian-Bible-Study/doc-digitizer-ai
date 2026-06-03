# AC Marchant Transcription Workspace

This directory contains working materials for transcribing the 1750 English Marchant translation of Arcana Coelestia Vol 2.

## Why This Set Matters

This translation is being used as an anchor reference for AI-assisted translation from Swedenborg's Latin into English. It is especially valuable because Marchant's work is understood to be the only English translation Swedenborg personally oversaw and reviewed.

## Directory Purpose

This is a single-work transcription workspace intended for use with the Python tooling from [doc-digitizer-ai](https://github.com/New-Christian-Bible-Study/doc-digitizer-ai) that uses AI for the transcribing.

## Directory Layout

- `source-pdfs/` - source scans used to generate chunks
- `chunk-pdfs/` - page-range chunk PDFs used for transcription runs
- `transcriptions/` - markdown transcriptions and AI log outputs
- `prompt.md` - transcription prompt for this workspace
- `transcribe.config.json` - model and transcription-response configuration
- `.review-chunk-state.json` - local review progress state

## Page Content to Ignore

This work is old enough that it has some unique markings on the pages that we want to ignore:
- Running heads (titles at the very top of pages).
- Ornaments and decorative horizontal bars.
- Signature marks and page numbers in the bottom margin (e.g., "A 2", "23181").
- Catchwords (the single word at the far bottom-right corner that anticipates the next page).