# sae: the owner's own SAE PDFs

The PDF stays in the research folder. The import writes an extraction and a search index under
`$PRIMARYSOURCE_HOME/sae` (on this machine, `D:\reference\sae`) and does not copy the PDF into the package
or into an image.

```
primarysource sae import D:\Research\volt\sae.j2534.2002.pdf --designation "SAE J2534:2002"
primarysource sae search "pass-through"
primarysource sae read "sae:j2534@2002"
```

A file named `sae.j2534.2002.pdf` does not need `--designation`. Refs are `sae:j2534@2002§<clause>`.
`pypdf` (the `iso` extra) is needed only while importing.

A scan with no bookmarks is read with Tesseract, one section per page. On that import `§` is the page
number, not a clause number from the standard. Tesseract is the `tesseract` executable on `PATH`, or
`%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe`. Documents already in the volume stay in the index.
