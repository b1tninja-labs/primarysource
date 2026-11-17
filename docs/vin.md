# vin: General Motors VIN standards filed with NHTSA

The `vin` collection serves the owner's copies of General Motors' vehicle-identification filings. Each one is GM's
VIN standard for a model year, submitted to NHTSA under 49 CFR Part 565. The 2016 letter cites 565.7. The 2017,
2018 and 2019 letters cite 565.16(c). A filing names CMVSS 115 and the ISO vehicle-identification standard and
does not give an ISO number, so the collection's label is `GM VIN standard <year>`.

```
pip install "primarysource[vin,mcp]"    # pypdf, needed only to import; mcp to serve
primarysource vin import                # every new or changed PDF in the vin home
primarysource vin search "Chevrolet Volt"
primarysource vin read vin:gm-vin-2016§33
primarysource mcp --collection vin      # vin_read, vin_search, vin_docs
```

## Where the files go

```
$PRIMARYSOURCE_VIN_HOME             # one collection on its own, e.g. D:\reference\vin
$PRIMARYSOURCE_HOME/vin             # otherwise
%LOCALAPPDATA%\primarysource\vin    # the default
```

The PDFs sit directly in that home. Import writes `extracted/`, `index.sqlite` and `install.json` beside them and
does not copy the PDF. Nothing here downloads a filing, and nothing reads Title 49 from the law library: the
Part 565 cite is the one printed on the filing's own cover.

On this machine the home is `D:\reference\vin` (`PRIMARYSOURCE_VIN_HOME`, or `PRIMARYSOURCE_HOME` pointing at
`D:\reference`). The shelf already holds `gm-vin-2016.pdf` through `gm-vin-2019.pdf`, imported one section per
page. `primarysource vin import` skips a file whose size and mtime are unchanged.

## What a ref is

`vin:gm-vin-2016§33` is PDF page 33 of the 2016 filing. `¶n` is the nth line of that page. Search hits are the
same refs. The section id is the page number because these filings are cut into pages, not numbered clauses.

This collection does not decode a VIN.
