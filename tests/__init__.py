"""시험 묶음."""

import logging

# 시험 중 래퍼가 남기는 경고와 오류 로그가 화면에 섞이지 않게 한다 (assertLogs 는 그대로 동작한다).
logging.getLogger("testgate").addHandler(logging.NullHandler())
