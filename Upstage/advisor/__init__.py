import os
import sys

# advisor/ 안의 모듈들(knowledge_base.py, advisor_agent.py, requirements.py 등)이
# 서로를 "import timetable_solver as T" 같은 평범한 절대 import로 참조한다.
# 이는 각 파일을 단독 스크립트로 실행할 때(python advisor/xxx.py)는 자동으로 되지만,
# 패키지로서 import될 때(server.py의 "from advisor import ...")는 안 되므로
# 이 폴더 자체를 sys.path에 등록해 두 경우 모두 동작하게 한다.
_ADVISOR_DIR = os.path.dirname(os.path.abspath(__file__))
if _ADVISOR_DIR not in sys.path:
    sys.path.insert(0, _ADVISOR_DIR)
