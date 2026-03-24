import csv
import os
from datetime import datetime


class CSVLogger:
    COLUMNS = ["id", "wbId", "name", "description", "tasting_1", "tasting_2", "mode", "timestamp"]

    def __init__(self, mode: str):
        os.makedirs("logs", exist_ok=True)
        self.filepath = "logs/scraper.csv"
        self._mode = mode
        file_exists = os.path.isfile(self.filepath)
        self._fh = open(self.filepath, "a", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._fh, fieldnames=self.COLUMNS)
        if not file_exists:
            self._writer.writeheader()
            self._fh.flush()

    def log(
        self,
        bottle_id: int,
        wb_id: str,
        name: str,
        desc_value: str,
        t1_value: str,
        t2_value: str,
    ) -> None:
        self._writer.writerow({
            "id": bottle_id,
            "wbId": wb_id,
            "name": name,
            "description": desc_value,
            "tasting_1": t1_value,
            "tasting_2": t2_value,
            "mode": self._mode,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        })
        self._fh.flush()

    def close(self) -> None:
        self._fh.close()
