"""モデルと起点状態の保存/復元。ストレージ・Codecを注入して使用する。"""

from dataclasses import replace

from ..contracts import ContextRef, ForecastDataset, ModelRef, ProviderConfig
from ..fingerprint import parameter_fingerprint
from ..run_context import RunContext, validate_context_ref
from . import json_format as jf
from .contracts import ArtifactError, ArtifactRef, ArtifactStore, StateCodec, verify_bytes
from .metadata import context_from_json, context_to_json, model_from_json, model_to_json

FORMAT_VERSION = 1
ENVELOPE_FIELDS = {
    "format_version",
    "kind",
    "codec_version",
    "provider_id",
    "binding",
    "metadata",
    "state",
    "model_artifact",
}


class ForecastArtifactRepository:
    def __init__(self, store: ArtifactStore, codecs: list[StateCodec]) -> None:
        self.store = store
        self.codecs = {}
        for codec in codecs:
            provider_id = codec.metadata().provider_id
            if provider_id in self.codecs:
                raise ArtifactError("重複したartifact codec")
            self.codecs[provider_id] = codec

    def _codec(self, provider_id: str) -> StateCodec:
        if provider_id not in self.codecs:
            raise ArtifactError("未対応のartifact provider")
        return self.codecs[provider_id]

    def _write(self, kind, config, context, metadata, state, model_artifact=None) -> ArtifactRef:
        codec = self._codec(config.provider_id)
        data = jf.dumps(
            {
                "format_version": FORMAT_VERSION,
                "kind": kind,
                "codec_version": codec.codec_version,
                "provider_id": config.provider_id,
                "binding": {
                    "run_id": jf.text(context.run_id),
                    "experiment_id": jf.text(context.experiment_id),
                },
                "metadata": metadata,
                "state": state,
                "model_artifact": model_artifact.to_dict() if model_artifact else None,
            }
        )
        ref = self.store.put(data)
        verify_bytes(ref, data)
        return ref

    def _read(self, artifact, kind, config, context) -> dict:
        data = self.store.get(artifact)
        verify_bytes(artifact, data)
        document = jf.loads(data)
        jf.keys(document, ENVELOPE_FIELDS)
        if jf.integer(document["format_version"]) != FORMAT_VERSION:
            raise ArtifactError("未対応のartifact format_version")
        if document["kind"] != kind or document["provider_id"] != config.provider_id:
            raise ArtifactError("artifact kind/provider不一致")
        codec = self._codec(config.provider_id)
        if jf.integer(document["codec_version"]) != codec.codec_version:
            raise ArtifactError("未対応のartifact codec_version")
        jf.keys(document["binding"], {"run_id", "experiment_id"})
        if document["binding"] != {
            "run_id": context.run_id,
            "experiment_id": context.experiment_id,
        }:
            raise ArtifactError("artifact run/experiment不一致")
        return document

    def _validate_model(self, model, dataset, config, context) -> StateCodec:
        context.validate_for_origin(dataset.train_end, dataset.availability_mode)
        codec = self._codec(config.provider_id)
        metadata = codec.metadata()
        expected = (
            metadata.provider_id,
            metadata.provider_version,
            config.model,
            config.preprocessing_version,
            dataset.train_start,
            dataset.train_end,
            dataset.availability_mode,
        )
        actual = (
            model.provider_id,
            model.provider_version,
            model.model_name,
            model.preprocessing_version,
            model.train_start_date,
            model.train_end_date,
            model.availability_mode,
        )
        if actual != expected:
            raise ArtifactError("artifactモデル条件/provider version不一致")
        expected_fingerprint = parameter_fingerprint(
            config, dataset, metadata, context, weights_id=model.weights_id
        )
        if model.parameter_fingerprint != expected_fingerprint:
            raise ArtifactError("artifact parameter_fingerprint不一致")
        return codec

    def save_model(
        self, model: ModelRef, dataset: ForecastDataset, config: ProviderConfig, context: RunContext
    ) -> ArtifactRef:
        codec = self._validate_model(model, dataset, config, context)
        state = codec.encode_model(model, dataset, config, context)
        return self._write("model", config, context, model_to_json(model), state)

    def load_model(
        self,
        artifact: ArtifactRef,
        dataset: ForecastDataset,
        config: ProviderConfig,
        context: RunContext,
    ) -> ModelRef:
        doc = self._read(artifact, "model", config, context)
        if doc["model_artifact"] is not None:
            raise ArtifactError("model artifactに親モデル参照は指定できません")
        model = model_from_json(doc["metadata"])
        codec = self._validate_model(model, dataset, config, context)
        loaded = codec.decode_model(doc["state"], model, dataset, config, context)
        return replace(loaded, artifact_uri=f"sha256:{artifact.sha256}")

    def save_context(
        self,
        ref: ContextRef,
        model_artifact: ArtifactRef,
        dataset: ForecastDataset,
        config: ProviderConfig,
        context: RunContext,
    ) -> ArtifactRef:
        model = self.load_model(
            model_artifact, dataset, config, context.for_origin(dataset.train_end)
        )
        validate_context_ref(model, ref, context)
        codec = self._codec(config.provider_id)
        return self._write(
            "context",
            config,
            context,
            context_to_json(ref),
            codec.encode_context(ref, model),
            model_artifact,
        )

    def load_context(
        self,
        artifact: ArtifactRef,
        model_artifact: ArtifactRef,
        dataset: ForecastDataset,
        config: ProviderConfig,
        context: RunContext,
    ) -> ContextRef:
        doc = self._read(artifact, "context", config, context)
        if ArtifactRef.from_dict(doc["model_artifact"]) != model_artifact:
            raise ArtifactError("contextのmodel artifact不一致")
        model = self.load_model(
            model_artifact, dataset, config, context.for_origin(dataset.train_end)
        )
        ref = context_from_json(doc["metadata"])
        validate_context_ref(model, ref, context)
        return self._codec(config.provider_id).decode_context(doc["state"], ref, model)
