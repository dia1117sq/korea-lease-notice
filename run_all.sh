#!/bin/bash
# 모든 공고 수집 (하루 1~2회 실행 권장)
cd "$(dirname "$0")"
python3 collect_myhome.py
python3 collect_lh.py
python3 enrich_lh_supply.py 100
python3 collect_applyhome.py
python3 merge.py
python3 build_site.py
