# Fixtures

Real input files the code is developed and tested against. Everything here is small
and committable - raw film is gitignored and stays on local disk.

## frames/
Native-resolution screenshots from broadcast film showing the score bug. Several per
season, plus at least one pre-snap / post-snap pair from the same play.
Used for: OCR crop coordinates, polarity detection, play-clock reset verification.

## hudl/
A real Hudl breakdown export (CSV or XLSX), with the actual column names your
coordinators use.
Used for: the importer and the column-mapping profile system.

## pbp/
One saved play-by-play page from the athletics site (HTML or the PDF export).
Used for: the PBP parser.

## clips/
Three or four pre-cut Hudl clips. NOTE: video is gitignored - keep these locally,
they will not be committed. Present so the clip-mapping code has something to run on.