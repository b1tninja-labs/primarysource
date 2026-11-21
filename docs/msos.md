# msos: Microsoft Open Specifications

The four families on [MS-OPENSPECLP](https://learn.microsoft.com/en-us/openspecs/main/ms-openspeclp/3589baea-5b22-48f2-9d43-f5bea4960ddb):
protocols, computer languages, standards support, and data portability. Each family page links a zip of the
published PDFs. `sync` reads that link and downloads the zip. `import` indexes each `[MS-...]` PDF.

```
primarysource msos sync
primarysource msos import
primarysource msos search "cabinet"
primarysource msos read "msos:ms-patch§2"
```

The zips stay in `$PRIMARYSOURCE_HOME/msos/zips/`. The package does not contain the documents. Microsoft's
notice on those pages allows copies for implementing the technologies; it does not make the text redistributable.
