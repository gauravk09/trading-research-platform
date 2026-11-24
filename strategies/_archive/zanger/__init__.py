"""Dan Zanger breakout scans, adapted for the Indian market.

Pure pandas functions over the precomputed universe summary table
(data/processed/universe_summary.parquet). No file or network I/O here — the
dashboard supplies the DataFrame. See SCAN_RULES.md for the rules and sources.
"""
