# DFAP Real Public Dataset Acquisition Guide

## 1. Overview & Research Provenance Policy

The DFAP platform enforces strict research integrity by distinguishing three provenance tiers:
1. **`REAL_PUBLIC_DATA`**: Authentic records downloaded directly from official research repositories. Must possess verified source file SHA-256 hashes and unaltered record identifiers.
2. **`SYNTHETIC_TEST_DATA`**: Isolated unit test fixture data located in `data/test_fixtures/` strictly utilized for automated CI regression testing.
3. **`CONTROLLED_CASE_MAPPING`**: Explicit cross-domain identity bridge entries (`data/cases/identity_bridge.parquet`) that connect identities across otherwise independent datasets for controlled research evaluation.

---

## 2. Official Dataset Manifest & Download Instructions

### A. Elliptic++ Bitcoin Graph Dataset
- **Official Paper:** Weber et al., *Anti-Money Laundering in Bitcoin: Experimenting with Graph Convolutional Networks for Financial Forensics*, KDD 2019.
- **Repository:** [https://github.com/git-disl/EllipticPlusPlus](https://github.com/git-disl/EllipticPlusPlus)
- **Kaggle Mirror:** [https://www.kaggle.com/datasets/ellipticco/elliptic-data-set](https://www.kaggle.com/datasets/ellipticco/elliptic-data-set)
- **License:** CC BY-NC-SA 4.0
- **Target Directory:** `data/sources/elliptic/`
- **Expected Files:**
  - `elliptic_txs.csv` (Transaction edge and feature list)
  - `elliptic_classes.csv` (Isolated ground-truth classification labels: 1=illicit, 2=licit, 3=unknown)
- **Manual Acquisition:**
  ```bash
  mkdir -p data/sources/elliptic
  # Place the official downloaded files into data/sources/elliptic/
  # Verify files exist:
  ls -lh data/sources/elliptic/elliptic_txs.csv data/sources/elliptic/elliptic_classes.csv
  ```

---

### B. UNSW-NB15 Network Intrusion Dataset
- **Official Paper:** Moustafa & Slay, *UNSW-NB15: a comprehensive data set for network intrusion detection systems*, MilCIS 2015.
- **Official Repository:** [https://research.unsw.edu.au/projects/unsw-nb15-dataset](https://research.unsw.edu.au/projects/unsw-nb15-dataset)
- **License:** Australian Centre for Cyber Security (ACCS) Educational/Research License
- **Target Directory:** `data/sources/unsw_nb15/`
- **Expected File:** `unsw_nb15_flows.csv`
- **Manual Acquisition:**
  ```bash
  mkdir -p data/sources/unsw_nb15
  # Place the official UNSW-NB15 CSV flow records into:
  # data/sources/unsw_nb15/unsw_nb15_flows.csv
  ```

---

### C. Stack Overflow Temporal Interaction Network
- **Official Paper:** Paranjape et al., *Motifs in Temporal Networks*, WSDM 2017.
- **Repository:** Stanford Network Analysis Project (SNAP) [https://snap.stanford.edu/data/sx-stackoverflow.html](https://snap.stanford.edu/data/sx-stackoverflow.html)
- **Direct Download:** `https://snap.stanford.edu/data/sx-stackoverflow.txt.gz`
- **License:** Public Domain / CC0
- **Target Directory:** `data/sources/stackoverflow/`
- **Expected File:** `stackoverflow_temporal.csv`
- **Acquisition Command:**
  ```bash
  mkdir -p data/sources/stackoverflow
  curl -o data/sources/stackoverflow/sx-stackoverflow.txt.gz https://snap.stanford.edu/data/sx-stackoverflow.txt.gz
  gunzip data/sources/stackoverflow/sx-stackoverflow.txt.gz
  head -n 50000 data/sources/stackoverflow/sx-stackoverflow.txt > data/sources/stackoverflow/stackoverflow_temporal.csv
  ```

---

## 3. Fail-Closed Real Data Ingestion Rule

When DFAP is run in `REAL_PUBLIC_DATA` mode (the default for `dfap ingest <dataset>`):
- If the required authentic files are missing from `data/sources/<dataset>/`, DFAP will **fail closed** with a typed `MissingRealDatasetError`.
- It will NOT fall back to synthetic data.
- It will print instructions directing the operator to this acquisition document.
