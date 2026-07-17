# Paper Trading project

This project's code is a thin layer over engines owned by sibling projects, so this
folder is a pointer rather than a package:

- **Frontend:** `frontend/src/components/paper_trading/PaperTradeView.tsx` — speed
  controls, live price/equity charts, running stats, trade log.
- **API route:** `POST /api/forecast/paper/stream` in `main.py` (`stream_paper_trade`),
  request schema `PaperRequest` in `models.py`. Routes for all projects live together
  in `main.py`.
- **Path generation:** `forward_testing/forecast.py` (`generate_one_path`) — the same
  synthetic-path engine the Forward Testing project owns.
- **Pipeline integration:** `reel_to_pipeline/pipeline.py` (`_run_paper_trading`) kicks
  off a background paper trade at the end of every Unified Pipeline run.
