# CREMA-D data

The manifest and derived CSV tables contain information from CREMA-D by Cao, Cooper, Keutmann, Gur, Nenkova, and Verma (2014), pinned at revision `1658cd342dff90010aa843eaeebd53610a08b1dc`. The Open Database License 1.0 applies to `data/manifest.csv` and the CREMA-D–derived CSV tables in `results/analysis/`. The Database Contents License 1.0 applies to the original CREMA-D contents. [Pinned CREMA-D dataset](https://github.com/CheyneyComputerScience/CREMA-D/tree/1658cd342dff90010aa843eaeebd53610a08b1dc) · [ODbL 1.0](https://opendatacommons.org/licenses/odbl/1-0/) · [DbCL 1.0](https://opendatacommons.org/licenses/dbcl/1-0/) · [Pinned upstream license notice](https://github.com/CheyneyComputerScience/CREMA-D/blob/1658cd342dff90010aa843eaeebd53610a08b1dc/LICENSE.txt) · [Cao et al. (2014)](https://doi.org/10.1109/TAFFC.2014.2336244)

Raw stimuli and individual ratings stay in the ignored local data directory. The source lock records hashes, exclusions and the rating filter. [Source lock](../SOURCE_LOCK.md#crema-d)

To retrieve and verify the pinned metadata and 300 sampled audio objects from the repository root, install the locked Python environment and run:

```powershell
$env:PYTHONPATH = 'src'
.venv/Scripts/python.exe -m intended_or_perceived.dataset --download
.venv/Scripts/python.exe -m intended_or_perceived.dataset
```

The derived tables in `results/analysis/` join to the manifest using the opaque `sample_id`. They include aggregate listener values, without individual listener identifiers or responses. [Derived table index](../results/analysis/RESULTS.md#figures-and-derived-data)
