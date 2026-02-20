"""
모델 버전 관리 및 로딩/저장 (Model Registry).
파일 시스템 또는 S3 기반의 모델 저장소 관리.
"""
import os
import pickle
import json
from typing import Any, Dict, Optional
from .utils import get_logger

logger = get_logger(__name__)


class ModelRegistry:
    """모델 레지스트리 관리 클래스."""

    def __init__(self, registry_path: str = "models/registry"):
        self.registry_path = registry_path
        os.makedirs(registry_path, exist_ok=True)
        self.metadata_file = os.path.join(registry_path, "metadata.json")
        self._is_dry_run = os.getenv("DRY_RUN", "True").lower() == "true"

    def load_model(self, version: str = "latest") -> Any:
        """지정된 버전(또는 최신)의 모델 로드."""
        logger.info(f"Loading model version: {version}")
        # 실제 구현: 피클 파일 로드 또는 ONNX 런타임 초기화
        # 여기서는 Mock 모델 객체 반환
        return MockModel(version=version)

    def save_model(self, model: Any, metadata: Dict[str, Any]) -> str:
        """모델 및 메타데이터 저장."""
        if self._is_dry_run:
            logger.info(f"[DRY_RUN] Saving model with metadata: {metadata}")
            return "v_dry_run"

        version = f"v_{int(datetime.now().timestamp())}"
        model_path = os.path.join(self.registry_path, f"{version}.pkl")
        
        # 모델 저장
        with open(model_path, "wb") as f:
            pickle.dump(model, f)
            
        # 메타데이터 업데이트
        self._update_metadata(version, metadata)
        logger.info(f"Model saved: {version}")
        return version

    def _update_metadata(self, version: str, meta: Dict[str, Any]):
        """메타데이터 파일 갱신 (원자적 쓰기 권장)."""
        current_data = {}
        if os.path.exists(self.metadata_file):
            with open(self.metadata_file, "r") as f:
                current_data = json.load(f)
        
        current_data[version] = meta
        current_data["latest"] = version
        
        with open(self.metadata_file, "w") as f:
            json.dump(current_data, f, indent=2)


class MockModel:
    """테스트용 모의 모델."""
    def __init__(self, version):
        self.version = version
    
    def predict(self, features):
        return {"slippage": 0.001, "split": 3}
