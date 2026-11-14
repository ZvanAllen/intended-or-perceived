# CREMA-D data

The derived manifest and vote counts are based on CREMA-D at revision `1658cd342dff90010aa843eaeebd53610a08b1dc`. The database is licensed under the Open Database License 1.0 and its contents under the Database Contents License 1.0. Raw stimuli and individual ratings stay in the ignored local data directory. See the source lock for hashes, exclusions and the rating filter. [Pinned upstream license](https://github.com/CheyneyComputerScience/CREMA-D/blob/1658cd342dff90010aa843eaeebd53610a08b1dc/LICENSE.txt) · [Cao et al. (2014)](https://doi.org/10.1109/TAFFC.2014.2336244)

To retrieve and verify the pinned metadata and 300 sampled audio objects from the repository root, install the locked Python environment and run:

```powershell
$env:PYTHONPATH = 'src'
.venv/Scripts/python.exe -m intended_or_perceived.dataset --download
.venv/Scripts/python.exe -m intended_or_perceived.dataset
```

The derived tables in `results/analysis/` join to the manifest using the opaque `sample_id`. They include aggregate listener values, without individual listener identifiers or responses. [Derived table index](../results/analysis/RESULTS.md#figures-and-derived-data)
