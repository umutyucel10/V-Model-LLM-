# -*- coding: utf-8 -*-

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

import mimari_cerceve_model as model


def _evidence(
    source_item_id="SGD-001",
    text="Sistem fren komutunu 100 ms içinde işlemelidir.",
):
    document = "Sistem Gereksinimleri"
    location = "Bölüm 4.2"
    return model.EvidenceLink(
        source_item_id=source_item_id,
        source_document=document,
        source_location=location,
        evidence_text=text,
        evidence_fingerprint=model.evidence_fingerprint_for(
            document, source_item_id, location, text,
        ),
        confidence_score=0.96,
        derivation_kind=model.DERIVATION_DIRECT,
        producer="etki_analizi_izlenebilirlik",
        producer_version="1.0",
    )


def _element(identity_key, name, element_type, requirement_id, evidence):
    return model.ArchitectureElement(
        identity_key=identity_key,
        framework_profile_id="dodaf",
        name=name,
        element_type=element_type,
        description=evidence.evidence_text,
        source_requirement_ids=(requirement_id,),
        evidence_text=evidence.evidence_text,
        confidence_score=0.94,
        evidence_links=(evidence,),
        review_status=model.REVIEW_PENDING,
        version="v0001",
        derivation_kind=model.DERIVATION_DETERMINISTIC,
    )


def _payload_evidence(evidence, *keys):
    return {key: (evidence.evidence_id,) for key in keys}


class ArchitectureModelJsonTests(unittest.TestCase):
    def test_all_contract_types_and_nested_snapshot_round_trip(self):
        evidence = _evidence()
        system = _element("SGD-001-fren", "Fren", "System", "SGD-001", evidence)
        function_evidence = _evidence("STT-003", "Alt sistem frenleme fonksiyonunu gerçekleştirmelidir.")
        function = _element("STT-003-frenleme", "Frenleme", "SystemFunction", "STT-003", function_evidence)
        relationship = model.ArchitectureRelationship(
            identity_key="STT-003-frenleme",
            framework_profile_id="dodaf",
            name="Frenleme",
            relationship_type="performed_by",
            source_element_id=function.stable_id,
            target_element_id=system.stable_id,
            description=function_evidence.evidence_text,
            source_requirement_ids=("STT-003", "SGD-001"),
            evidence_text=function_evidence.evidence_text,
            confidence_score=0.91,
            evidence_links=(function_evidence, evidence),
            derivation_kind=model.DERIVATION_DETERMINISTIC,
        )
        proposal = model.CandidateProposal(
            identity_key="STT-003-frenleme",
            framework_profile_id="dodaf",
            proposal_type="relationship",
            title="Operasyonel faaliyet eşlemesi",
            rationale="Kaynakta faaliyet ve fonksiyon aynı frenleme davranışına bağlıdır.",
            proposed_payload={
                "identity_key": "STT-003-frenleme",
                "name": "Frenleme",
                "relationship_type": "maps_to",
                "description": function_evidence.evidence_text,
            },
            payload_evidence_ids={
                "identity_key": (function_evidence.evidence_id,),
                "name": (function_evidence.evidence_id,),
                "relationship_type": (evidence.evidence_id,),
                "description": (function_evidence.evidence_id,),
            },
            source_requirement_ids=("SGD-001", "STT-003"),
            evidence_text=evidence.evidence_text,
            confidence_score=0.78,
            evidence_links=(evidence, function_evidence),
            source_element_id=system.stable_id,
            target_element_id=function.stable_id,
        )
        decision = model.ReviewDecision.for_proposal(
            proposal,
            model.DECISION_ACCEPT,
            "Sistem Mimarı",
            "2026-08-12T18:00:00+03:00",
            rationale="Kaynaklar incelendi.",
        )
        finding = model.ValidationFinding(
            code="missing_timeframe",
            severity="warning",
            message="SV-7 için zaman ufku belirsiz/eksik.",
            target_id=system.stable_id,
            view_id="SV-7",
            missing_fields=("timeframe",),
            evidence_ids=(evidence.evidence_id,),
            blocking=True,
        )
        snapshot = model.ArchitectureSnapshot(
            identity_key="fren-mimarisi",
            project_id="fren-3ac30dd0",
            name="Fren Sistemi Mimari Taslağı",
            framework_profile_id="dodaf",
            framework_version="2.02",
            version="v0001",
            status=model.SNAPSHOT_DRAFT,
            created_at="2026-08-12T18:01:00+03:00",
            elements=(system, function),
            relationships=(relationship,),
            candidate_proposals=(proposal,),
            review_decisions=(decision,),
            validation_findings=(finding,),
            selected_view_ids=("SV-1", "SV-4", "SV-7"),
        )

        payload = json.loads(json.dumps(snapshot.to_dict(), ensure_ascii=False))
        restored = model.ArchitectureSnapshot.from_dict(payload)

        self.assertEqual(restored.to_dict(), snapshot.to_dict())
        self.assertIsInstance(restored.elements[0], model.ArchitectureElement)
        self.assertIsInstance(restored.relationships[0], model.ArchitectureRelationship)
        self.assertIsInstance(restored.candidate_proposals[0], model.CandidateProposal)
        self.assertIsInstance(restored.review_decisions[0], model.ReviewDecision)
        self.assertIsInstance(restored.validation_findings[0], model.ValidationFinding)
        self.assertIsInstance(restored.elements[0].evidence_links[0], model.EvidenceLink)

        detached = snapshot.to_dict()
        detached["elements"][0]["name"] = "Değiştirildi"
        detached["candidate_proposals"][0]["proposed_payload"]["name"] = "X"
        self.assertEqual(snapshot.elements[0].name, "Fren")
        self.assertNotEqual("X", snapshot.candidate_proposals[0].proposed_payload["name"])

    def test_view_and_profile_round_trip(self):
        view = model.ViewDefinition(
            framework_profile_id="test",
            framework_version="1.0",
            view_id="T-1",
            name="Test View",
            purpose="Test amacı",
            required_element_types=("Node",),
            required_relationships=("connects",),
            data_prerequisites=("Kanıtlı iki uç",),
            export_type="diagram",
            package="test_package",
            required_any_of_element_types=(("Node", "Role"),),
            required_any_of_relationships=(("uses", "performs"),),
        )
        profile = model.FrameworkProfile(
            profile_id="test",
            name="Test Framework",
            version="1.0",
            description="Yalnızca JSON testi için profil.",
            view_definitions=(view,),
        )
        payload = json.loads(json.dumps(profile.to_dict(), ensure_ascii=False))
        restored = model.FrameworkProfile.from_dict(payload)
        self.assertEqual(restored.to_dict(), profile.to_dict())
        self.assertIsInstance(restored.view_definitions[0], model.ViewDefinition)
        self.assertEqual(restored.view_definitions[0].required_any_of_element_types, (("Node", "Role"),))


class StableIdentityTests(unittest.TestCase):
    def test_element_identity_ignores_order_and_mutable_presentation_fields(self):
        evidence = _evidence()
        second_evidence = _evidence("STT-002", "Kontrol birimi alt sistem işlevini yürütür.")
        base = model.ArchitectureElement(
            identity_key="STT-002-kontrol",
            framework_profile_id="dodaf",
            name="Kontrol Birimi",
            element_type="System",
            description=second_evidence.evidence_text,
            source_requirement_ids=("STT-002", "SGD-001"),
            evidence_text=evidence.evidence_text,
            confidence_score=0.90,
            evidence_links=(evidence, second_evidence),
            version="v0001",
        )
        updated_evidence = _evidence(
            "SGD-001", "Ana kontrol birimi fren komutlarını yönetmelidir.",
        )
        renamed = model.ArchitectureElement(
            identity_key="STT-002-kontrol",
            framework_profile_id="dodaf",
            name="Alt Sistem",
            element_type="System",
            description=updated_evidence.evidence_text,
            source_requirement_ids=("SGD-001", "STT-002", "SGD-001"),
            evidence_text=updated_evidence.evidence_text,
            confidence_score=0.71,
            evidence_links=(updated_evidence, second_evidence),
            version="v0009",
        )
        other = model.ArchitectureElement(
            identity_key="SGD-001-fren",
            framework_profile_id="dodaf",
            name="Fren",
            element_type="System",
            description=evidence.evidence_text,
            source_requirement_ids=("SGD-001", "STT-002"),
            evidence_text=evidence.evidence_text,
            confidence_score=0.9,
            evidence_links=(evidence, second_evidence),
        )
        self.assertEqual(base.stable_id, renamed.stable_id)
        self.assertNotEqual(base.stable_id, other.stable_id)
        self.assertNotEqual(
            model.stable_id_for("ARCH-ELEMENT", "aynı"),
            model.stable_id_for("ARCH-REL", "aynı"),
        )

        third_evidence = _evidence("SGD-010", "Aynı birim için ek destekleyici gereksinim.")
        expanded = model.ArchitectureElement(
            identity_key="STT-002-kontrol",
            framework_profile_id="dodaf",
            name="Kontrol Birimi",
            element_type="System",
            description=second_evidence.evidence_text,
            source_requirement_ids=("SGD-001", "STT-002", "SGD-010"),
            evidence_text=evidence.evidence_text,
            confidence_score=0.92,
            evidence_links=(evidence, second_evidence, third_evidence),
            version="v0010",
        )
        self.assertEqual(base.stable_id, expanded.stable_id)

    def test_from_dict_preserves_persisted_stable_id(self):
        evidence = _evidence()
        original = _element("SGD-001-fren", "Fren", "System", "SGD-001", evidence)
        payload = original.to_dict()
        payload["stable_id"] = "KALICI-KIMLIK-001"
        restored = model.ArchitectureElement.from_dict(payload)
        self.assertEqual(restored.stable_id, "KALICI-KIMLIK-001")

    def test_stable_id_is_independent_of_python_hash_seed(self):
        root = Path(__file__).resolve().parents[1]
        script = (
            "from mimari_cerceve_model import stable_id_for; "
            "print(stable_id_for('ARCH-ELEMENT', "
            "{'type':'System','requirements':['STT-2','SGD-1']}))"
        )
        outputs = []
        for seed in ("1", "987"):
            environment = dict(os.environ, PYTHONHASHSEED=seed)
            outputs.append(subprocess.check_output(
                [sys.executable, "-X", "utf8", "-c", script],
                cwd=root, env=environment, text=True,
            ).strip())
        self.assertEqual(outputs[0], outputs[1])

    def test_relationship_and_proposal_identity_survive_added_evidence(self):
        first = _evidence(text="Sistemler arasında fren bağlantısı kurulmalıdır.")
        second = _evidence("STT-002", "Ek gereksinim aynı ilişkiyi destekler.")
        relationship_arguments = dict(
            identity_key="SGD-001-fren",
            framework_profile_id="dodaf",
            name="Fren",
            relationship_type="connects",
            source_element_id="ARCH-ELEMENT-A",
            target_element_id="ARCH-ELEMENT-B",
            description=first.evidence_text,
            evidence_text=first.evidence_text,
            confidence_score=0.8,
        )
        original = model.ArchitectureRelationship(
            **relationship_arguments,
            source_requirement_ids=("SGD-001",),
            evidence_links=(first,),
            version="v0001",
        )
        expanded = model.ArchitectureRelationship(
            **relationship_arguments,
            source_requirement_ids=("SGD-001", "STT-002"),
            evidence_links=(first, second),
            version="v0002",
        )
        self.assertEqual(original.stable_id, expanded.stable_id)

        payload_one = {
            "identity_key": "SGD-001-fren",
            "name": "Fren",
            "element_type": "System",
            "description": first.evidence_text,
        }
        payload_two = dict(payload_one)
        proposal_one = model.CandidateProposal(
            identity_key="SGD-001-fren",
            framework_profile_id="dodaf",
            proposal_type="element",
            title="Aday Sistem",
            rationale="İlk gerekçe",
            proposed_payload=payload_one,
            payload_evidence_ids=_payload_evidence(first, *payload_one.keys()),
            source_requirement_ids=("SGD-001",),
            evidence_text=first.evidence_text,
            confidence_score=0.7,
            evidence_links=(first,),
        )
        proposal_two = model.CandidateProposal(
            identity_key="SGD-001-fren",
            framework_profile_id="dodaf",
            proposal_type="element",
            title="Aday Sistem",
            rationale="Yeni kaynakla güncellendi",
            proposed_payload=payload_two,
            payload_evidence_ids={
                key: (first.evidence_id, second.evidence_id) for key in payload_two
            },
            source_requirement_ids=("SGD-001", "STT-002"),
            evidence_text=first.evidence_text,
            confidence_score=0.8,
            evidence_links=(first, second),
            version="v0002",
        )
        self.assertEqual(proposal_one.proposal_id, proposal_two.proposal_id)
        self.assertNotEqual(model.proposal_digest(proposal_one), model.proposal_digest(proposal_two))


class EvidenceAndReviewGateTests(unittest.TestCase):
    def test_automatic_element_relationship_and_candidate_require_source_evidence(self):
        arguments = dict(
            identity_key="kanitsiz",
            framework_profile_id="dodaf",
            name="Kanıtsız Sistem",
            element_type="System",
            description="Otomatik kayıt",
            source_requirement_ids=("SGD-001",),
            evidence_text="Yalnızca model metni",
            confidence_score=0.8,
            evidence_links=(),
        )
        with self.assertRaisesRegex(ValueError, "kaynak kanıtı"):
            model.ArchitectureElement(**arguments)

        suggestion_only = model.EvidenceLink(
            source_item_id="SGD-001",
            source_document="Model yanıtı",
            source_location="Gemma",
            evidence_text="Gemma tarafından önerildi.",
            evidence_fingerprint=model.evidence_fingerprint_for(
                "Model yanıtı", "SGD-001", "Gemma", "Gemma tarafından önerildi.",
            ),
            confidence_score=0.7,
            derivation_kind=model.DERIVATION_MODEL_SUGGESTION,
            producer="Gemma",
            producer_version="yerel-model",
        )
        arguments["evidence_links"] = (suggestion_only,)
        with self.assertRaisesRegex(ValueError, "kaynak kanıtı"):
            model.ArchitectureElement(**arguments)

        source_evidence = _evidence()
        unrelated_evidence = _evidence(
            text="Güç girişi 28 V olmalıdır.",
        )
        with self.assertRaisesRegex(ValueError, "kaynak kanıtıyla ilişkilendirilemedi"):
            model.ArchitectureElement(
                identity_key="ejderha-servisi",
                framework_profile_id="dodaf",
                name="Ejderha Teleport Hizmeti",
                element_type="Service",
                description="Kurumsal işlev.",
                source_requirement_ids=("SGD-001",),
                evidence_text=unrelated_evidence.evidence_text,
                confidence_score=0.8,
                evidence_links=(unrelated_evidence,),
                derivation_kind=model.DERIVATION_DETERMINISTIC,
            )
        type_evidence = _evidence(
            text="Fren sistemi komutu işlemelidir.",
        )
        with self.assertRaisesRegex(ValueError, "entity_type"):
            model.ArchitectureElement(
                identity_key="SGD-001-fren",
                framework_profile_id="dodaf",
                name="Fren",
                element_type="DragonTeleportService",
                description=type_evidence.evidence_text,
                source_requirement_ids=("SGD-001",),
                evidence_text=type_evidence.evidence_text,
                confidence_score=0.8,
                evidence_links=(type_evidence,),
                derivation_kind=model.DERIVATION_DETERMINISTIC,
            )
        mixed_context = _evidence(
            text="Motor A fren sağlar. Motor B güç sağlar.",
        )
        with self.assertRaisesRegex(ValueError, "description"):
            model.ArchitectureElement(
                identity_key="SGD-001-motor-a",
                framework_profile_id="dodaf",
                name="Motor A",
                element_type="System",
                description="Motor A güç sağlar.",
                source_requirement_ids=("SGD-001",),
                evidence_text=mixed_context.evidence_text,
                confidence_score=0.8,
                evidence_links=(mixed_context,),
                derivation_kind=model.DERIVATION_DETERMINISTIC,
            )
        arguments["evidence_links"] = (source_evidence,)
        arguments["evidence_text"] = source_evidence.evidence_text
        arguments["derivation_kind"] = model.DERIVATION_MODEL_SUGGESTION
        with self.assertRaisesRegex(ValueError, "onay"):
            model.ArchitectureElement(**arguments)

        with self.assertRaisesRegex(ValueError, "kaynak kanıtı"):
            model.CandidateProposal(
                identity_key="aday",
                framework_profile_id="dodaf",
                proposal_type="element",
                title="Kanıtsız aday",
                rationale="Model yorumu",
                proposed_payload={
                    "identity_key": "aday",
                    "name": "Kanıtsız",
                    "element_type": "System",
                    "description": "Model yorumu",
                },
                source_requirement_ids=("SGD-001",),
                evidence_text="Model yorumu",
                confidence_score=0.5,
                evidence_links=(),
            )

    def test_evidence_requires_source_identity_location_text_and_fingerprint(self):
        valid = dict(
            source_item_id="SGD-001",
            source_document="SGD",
            source_location="Bölüm 1",
            evidence_text="Kanıt",
            evidence_fingerprint=model.evidence_fingerprint_for(
                "SGD", "SGD-001", "Bölüm 1", "Kanıt",
            ),
            confidence_score=0.9,
            producer="test",
            producer_version="1.0",
        )
        for field in (
            "source_item_id", "source_document", "source_location",
            "evidence_text", "evidence_fingerprint",
        ):
            values = dict(valid)
            values[field] = "  "
            with self.subTest(field=field), self.assertRaises(ValueError):
                model.EvidenceLink(**values)

        tampered = dict(valid)
        tampered["evidence_text"] = "Değiştirilmiş kanıt"
        with self.assertRaisesRegex(ValueError, "uyuşmuyor"):
            model.EvidenceLink(**tampered)

    def test_user_input_reaches_canonical_model_only_through_explicit_acceptance(self):
        text = "Mühendis, mimari öğe adını Fren Denetleyicisi olarak belirledi."
        user_evidence = model.EvidenceLink(
            source_item_id="USER-INPUT-001",
            source_document="Mimari kullanıcı girdisi",
            source_location="Öğe düzenleme formu",
            evidence_text=text,
            evidence_fingerprint=model.evidence_fingerprint_for(
                "Mimari kullanıcı girdisi", "USER-INPUT-001", "Öğe düzenleme formu", text,
            ),
            confidence_score=1.0,
            derivation_kind=model.DERIVATION_USER_SUPPLIED,
            producer="mimari_onay",
            producer_version="1.0",
        )
        with self.assertRaisesRegex(ValueError, "kaynak kanıtı"):
            model.ArchitectureElement(
                identity_key="otomatik-gibi",
                framework_profile_id="dodaf",
                name="Otomatik Gibi",
                element_type="System",
                description="Kullanıcı girdisi otomatik kanıt gibi kullanılamaz.",
                source_requirement_ids=(),
                evidence_text=text,
                confidence_score=1.0,
                evidence_links=(user_evidence,),
                derivation_kind=model.DERIVATION_DIRECT,
            )
        with self.assertRaisesRegex(ValueError, "kaynak gereksinimlerinin kanıt bağı"):
            model.CandidateProposal(
                identity_key="sahte-kaynak-id",
                framework_profile_id="dodaf",
                proposal_type="element",
                title="Kaynak kimliği desteklenmeyen kullanıcı adayı",
                rationale="Kullanıcı girdisi kaynak gereksinim kanıtı değildir.",
                proposed_payload={
                    "identity_key": "sahte-kaynak-id",
                    "name": "Sahte kaynak",
                    "element_type": "System",
                    "description": "Kullanıcı girdisi kaynak gereksinim kanıtı değildir.",
                },
                payload_evidence_ids=_payload_evidence(
                    user_evidence,
                    "identity_key", "name", "element_type", "description",
                ),
                source_requirement_ids=("SGD-999",),
                evidence_text=text,
                confidence_score=1.0,
                evidence_links=(user_evidence,),
                proposal_origin=model.DERIVATION_USER_SUPPLIED,
            )
        with self.assertRaisesRegex(ValueError, "(?i)onay"):
            model.ArchitectureElement(
                identity_key="fren-denetleyicisi",
                framework_profile_id="dodaf",
                name="Fren Denetleyicisi",
                element_type="System",
                description="Kullanıcı tarafından girilen sistem öğesi.",
                source_requirement_ids=(),
                evidence_text=text,
                confidence_score=1.0,
                evidence_links=(user_evidence,),
                review_status=model.REVIEW_APPROVED,
                derivation_kind=model.DERIVATION_USER_SUPPLIED,
            )

        proposal = model.CandidateProposal(
            identity_key="fren-denetleyicisi",
            framework_profile_id="dodaf",
            proposal_type="element",
            title="Fren Denetleyicisi",
            rationale="Kullanıcı girdisi ayrı aday olarak incelenir.",
            proposed_payload={
                "identity_key": "fren-denetleyicisi",
                "name": "Fren Denetleyicisi",
                "element_type": "System",
                "description": text,
            },
            payload_evidence_ids=_payload_evidence(
                user_evidence,
                "identity_key", "name", "element_type", "description",
            ),
            source_requirement_ids=(),
            evidence_text=text,
            confidence_score=1.0,
            evidence_links=(user_evidence,),
            proposal_origin=model.DERIVATION_USER_SUPPLIED,
        )
        decision = model.ReviewDecision.for_proposal(
            proposal,
            model.DECISION_ACCEPT,
            "Sistem Mimarı",
            "2026-08-12T18:30:00+03:00",
        )
        element = model.ArchitectureElement(
            identity_key="fren-denetleyicisi",
            framework_profile_id="dodaf",
            name="Fren Denetleyicisi",
            element_type="System",
            description=text,
            source_requirement_ids=(),
            evidence_text=text,
            confidence_score=1.0,
            evidence_links=(user_evidence,),
            review_status=model.REVIEW_APPROVED,
            derivation_kind=model.DERIVATION_USER_SUPPLIED,
            source_proposal_id=proposal.proposal_id,
            approval_decision_id=decision.decision_id,
        )
        snapshot = model.ArchitectureSnapshot(
            identity_key="kullanici-girdisi",
            project_id="p-user",
            name="Kullanıcı Girdisi Taslağı",
            framework_profile_id="dodaf",
            framework_version="2.02",
            version="v0001",
            status=model.SNAPSHOT_DRAFT,
            created_at="2026-08-12T18:31:00+03:00",
            elements=(element,),
            candidate_proposals=(proposal,),
            review_decisions=(decision,),
        )
        self.assertEqual(snapshot.elements[0].approval_decision_id, decision.decision_id)

        different_element = model.ArchitectureElement(
            identity_key="baska-sistem",
            framework_profile_id="dodaf",
            name="Başka Sistem",
            element_type="Service",
            description="Onaylanan adaydan farklı içerik.",
            source_requirement_ids=(),
            evidence_text=text,
            confidence_score=1.0,
            evidence_links=(user_evidence,),
            review_status=model.REVIEW_APPROVED,
            derivation_kind=model.DERIVATION_USER_SUPPLIED,
            source_proposal_id=proposal.proposal_id,
            approval_decision_id=decision.decision_id,
        )
        with self.assertRaisesRegex(ValueError, "onaylanan adayla uyuşmuyor"):
            model.ArchitectureSnapshot(
                identity_key="yanlis-kanonik-icerik",
                project_id="p-user",
                name="Yanlış Kanonik İçerik",
                framework_profile_id="dodaf",
                framework_version="2.02",
                version="v0001",
                status=model.SNAPSHOT_DRAFT,
                created_at="2026-08-12T18:32:00+03:00",
                elements=(different_element,),
                candidate_proposals=(proposal,),
                review_decisions=(decision,),
            )

    def test_model_cannot_self_approve_and_candidate_defaults_to_deferred(self):
        evidence = _evidence(text="Fren sistemi başka sisteme bağlantı kurmalıdır.")
        proposal = model.CandidateProposal(
            identity_key="SGD-001-fren",
            framework_profile_id="dodaf",
            proposal_type="element",
            title="Kanıtlı aday",
            rationale="Kaynakta sistem adayı var.",
            proposed_payload={
                "identity_key": "SGD-001-fren",
                "name": "Fren",
                "element_type": "System",
                "description": evidence.evidence_text,
            },
            payload_evidence_ids=_payload_evidence(
                evidence,
                "identity_key", "name", "element_type", "description",
            ),
            source_requirement_ids=("SGD-001",),
            evidence_text=evidence.evidence_text,
            confidence_score=0.77,
            evidence_links=(evidence,),
        )
        self.assertEqual(proposal.review_status, model.REVIEW_PENDING)
        self.assertEqual(proposal.initial_decision, model.DECISION_DEFER)
        with self.assertRaisesRegex(ValueError, "onaylayamaz"):
            model.ReviewDecision(
                candidate_id=proposal.proposal_id,
                decision=model.DECISION_ACCEPT,
                actor_type=model.ACTOR_MODEL,
                actor="Gemma",
                decided_at="2026-08-12T18:00:00+03:00",
                candidate_digest=model.proposal_digest(proposal),
            )
        with self.assertRaisesRegex(ValueError, "aktör, zaman"):
            model.ReviewDecision(
                candidate_id=proposal.proposal_id,
                decision=model.DECISION_DEFER,
                actor_type=model.ACTOR_MODEL,
                actor="",
                decided_at="",
                candidate_digest="",
            )

    def test_candidate_payload_claims_require_field_evidence_and_typed_references(self):
        evidence = _evidence(
            text="Fren komutu, kaynak ve hedef sistemler arasında taşınır.",
        )
        model_text = "Gemma aday ilişki alanlarını önerdi."
        model_evidence = model.EvidenceLink(
            source_item_id="MODEL-OUTPUT-1",
            source_document="Gemma yanıtı",
            source_location="Aday üretimi",
            evidence_text=model_text,
            evidence_fingerprint=model.evidence_fingerprint_for(
                "Gemma yanıtı", "MODEL-OUTPUT-1", "Aday üretimi", model_text,
            ),
            confidence_score=0.6,
            derivation_kind=model.DERIVATION_MODEL_SUGGESTION,
            producer="Gemma",
            producer_version="yerel-model",
        )
        payload = {
            "identity_key": "fren-komutu",
            "name": "Fren Komutu",
            "relationship_type": "connects",
            "description": evidence.evidence_text,
        }
        with self.assertRaisesRegex(ValueError, "uygun kaynak/girdi kanıtı"):
            model.CandidateProposal(
                identity_key="fren-komutu",
                framework_profile_id="dodaf",
                proposal_type="relationship",
                title="Bağlantı adayı",
                rationale="Model metni kaynak kanıtı değildir.",
                proposed_payload=payload,
                payload_evidence_ids=_payload_evidence(model_evidence, *payload.keys()),
                source_requirement_ids=("SGD-001",),
                evidence_text=evidence.evidence_text,
                confidence_score=0.7,
                evidence_links=(evidence, model_evidence),
                source_element_id="ARCH-ELEMENT-A",
                target_element_id="ARCH-ELEMENT-B",
            )
        with self.assertRaisesRegex(ValueError, "kanıtsız alanlar"):
            model.CandidateProposal(
                identity_key="fren-komutu",
                framework_profile_id="dodaf",
                proposal_type="relationship",
                title="Bağlantı adayı",
                rationale="Her iddia ayrı kanıta bağlanmalıdır.",
                proposed_payload=payload,
                payload_evidence_ids=_payload_evidence(
                    evidence,
                    "identity_key", "name", "relationship_type",
                ),
                source_requirement_ids=("SGD-001",),
                evidence_text=evidence.evidence_text,
                confidence_score=0.7,
                evidence_links=(evidence,),
                source_element_id="ARCH-ELEMENT-A",
                target_element_id="ARCH-ELEMENT-B",
            )

        reserved_payload = dict(payload)
        reserved_payload["target_element_id"] = "UNKNOWN"
        with self.assertRaisesRegex(ValueError, "kanoniğe kayıpsız"):
            model.CandidateProposal(
                identity_key="fren-komutu",
                framework_profile_id="dodaf",
                proposal_type="relationship",
                title="Bağlantı adayı",
                rationale="Referans serbest JSON içinde tutulamaz.",
                proposed_payload=reserved_payload,
                payload_evidence_ids=_payload_evidence(evidence, *reserved_payload.keys()),
                source_requirement_ids=("SGD-001",),
                evidence_text=evidence.evidence_text,
                confidence_score=0.7,
                evidence_links=(evidence,),
                source_element_id="ARCH-ELEMENT-A",
                target_element_id="ARCH-ELEMENT-B",
            )

        unsupported_payload = dict(payload, description="Sistem 999 V ile UYDURMA-PROTOKOL kullanır.")
        with self.assertRaisesRegex(ValueError, "kaynak kanıt"):
            model.CandidateProposal(
                identity_key="fren-komutu",
                framework_profile_id="dodaf",
                proposal_type="relationship",
                title="Bağlantı adayı",
                rationale="Kaynaksız protokol ve sayı reddedilmelidir.",
                proposed_payload=unsupported_payload,
                payload_evidence_ids=_payload_evidence(evidence, *unsupported_payload.keys()),
                source_requirement_ids=("SGD-001",),
                evidence_text=evidence.evidence_text,
                confidence_score=0.7,
                evidence_links=(evidence,),
                source_element_id="ARCH-ELEMENT-A",
                target_element_id="ARCH-ELEMENT-B",
            )

        mixed_case_protocol = dict(
            payload,
            description="Sistem uydurma-protokol kullanır.",
        )
        with self.assertRaisesRegex(ValueError, "kaynak kanıt"):
            model.CandidateProposal(
                identity_key="fren-komutu",
                framework_profile_id="dodaf",
                proposal_type="relationship",
                title="Bağlantı adayı",
                rationale="Küçük harfli teknik iddia da kanıta bağlı olmalıdır.",
                proposed_payload=mixed_case_protocol,
                payload_evidence_ids=_payload_evidence(evidence, *mixed_case_protocol.keys()),
                source_requirement_ids=("SGD-001",),
                evidence_text=evidence.evidence_text,
                confidence_score=0.7,
                evidence_links=(evidence,),
                source_element_id="ARCH-ELEMENT-A",
                target_element_id="ARCH-ELEMENT-B",
            )

        unrelated_payload = {
            "identity_key": "ejderha-servisi",
            "name": "Ejderha Teleport Hizmeti",
            "element_type": "Service",
            "description": "Kurumsal işlev.",
        }
        with self.assertRaisesRegex(ValueError, "yorum alanı kaynak kanıtıyla"):
            model.CandidateProposal(
                identity_key="ejderha-servisi",
                framework_profile_id="dodaf",
                proposal_type="element",
                title="İlgisiz aday",
                rationale="İlgisiz kaynak bağı aday için yeterli değildir.",
                proposed_payload=unrelated_payload,
                payload_evidence_ids=_payload_evidence(evidence, *unrelated_payload.keys()),
                source_requirement_ids=("SGD-001",),
                evidence_text=evidence.evidence_text,
                confidence_score=0.7,
                evidence_links=(evidence,),
            )

        camel_case_reference = dict(payload)
        camel_case_reference["targetStableId"] = "UNKNOWN"
        with self.assertRaisesRegex(ValueError, "kanoniğe kayıpsız"):
            model.CandidateProposal(
                identity_key="baglanti-adayi",
                framework_profile_id="dodaf",
                proposal_type="relationship",
                title="Bağlantı adayı",
                rationale="Kimlik alanı serbest yükte taşınamaz.",
                proposed_payload=camel_case_reference,
                payload_evidence_ids=_payload_evidence(evidence, *camel_case_reference.keys()),
                source_requirement_ids=("SGD-001",),
                evidence_text=evidence.evidence_text,
                confidence_score=0.7,
                evidence_links=(evidence,),
                source_element_id="ARCH-ELEMENT-A",
                target_element_id="ARCH-ELEMENT-B",
            )

        source = _element("kaynak", "Kaynak", "System", "SGD-001", evidence)
        valid_mapping = _payload_evidence(evidence, *payload.keys())
        orphan_target = model.CandidateProposal(
            identity_key="fren-komutu",
            framework_profile_id="dodaf",
            proposal_type="relationship",
            title="Bağlantı adayı",
            rationale="Uçlar snapshot bütünlüğünde doğrulanır.",
            proposed_payload=payload,
            payload_evidence_ids=valid_mapping,
            source_requirement_ids=("SGD-001",),
            evidence_text=evidence.evidence_text,
            confidence_score=0.7,
            evidence_links=(evidence,),
            source_element_id=source.stable_id,
            target_element_id="ARCH-ELEMENT-YOK",
        )
        with self.assertRaisesRegex(ValueError, "İlişki adayının hedef öğesi"):
            model.ArchitectureSnapshot(
                identity_key="yetim-aday-ucu",
                project_id="p1",
                name="Yetim Aday Ucu",
                framework_profile_id="dodaf",
                framework_version="2.02",
                version="v0001",
                status=model.SNAPSHOT_DRAFT,
                created_at="2026-08-12T18:40:00+03:00",
                elements=(source,),
                candidate_proposals=(orphan_target,),
            )

    def test_short_turkish_names_can_be_grounded_exactly(self):
        for index, (name, element_type) in enumerate(
            (("İHA", "System"), ("Sistem", "System"), ("Servis", "Service")),
            start=1,
        ):
            evidence = _evidence(f"REQ-{index}", name)
            payload = {
                "identity_key": name,
                "name": name,
                "element_type": element_type,
                "description": name,
            }
            with self.subTest(name=name):
                proposal = model.CandidateProposal(
                    identity_key=name,
                    framework_profile_id="dodaf",
                    proposal_type="element",
                    title=f"{name} adayı",
                    rationale="Kaynakla birebir eşleşen kısa ad.",
                    proposed_payload=payload,
                    payload_evidence_ids=_payload_evidence(evidence, *payload.keys()),
                    source_requirement_ids=(f"REQ-{index}",),
                    evidence_text=evidence.evidence_text,
                    confidence_score=0.8,
                    evidence_links=(evidence,),
                )
                self.assertEqual(proposal.proposed_payload["name"], name)

    def test_invalid_confidence_and_dangling_snapshot_relationship_are_rejected(self):
        for value in (True, -0.1, 1.1, float("nan"), float("inf")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                model.EvidenceLink(
                    source_item_id="SGD-001",
                    source_document="SGD",
                    source_location="Bölüm 1",
                    evidence_text="Kanıt",
                    evidence_fingerprint=model.evidence_fingerprint_for(
                        "SGD", "SGD-001", "Bölüm 1", "Kanıt",
                    ),
                    confidence_score=value,
                    producer="test",
                    producer_version="1.0",
                )

        evidence = _evidence(text="Fren sistemi başka sisteme bağlantı kurmalıdır.")
        element = _element("SGD-001-fren", "Fren", "System", "SGD-001", evidence)
        dangling = model.ArchitectureRelationship(
            identity_key="SGD-001-fren",
            framework_profile_id="dodaf",
            name="Fren",
            relationship_type="connects",
            source_element_id=element.stable_id,
            target_element_id="ARCH-ELEMENT-YOK",
            description=evidence.evidence_text,
            source_requirement_ids=("SGD-001",),
            evidence_text=evidence.evidence_text,
            confidence_score=0.8,
            evidence_links=(evidence,),
        )
        with self.assertRaisesRegex(ValueError, "hedef öğesi"):
            model.ArchitectureSnapshot(
                identity_key="kopuk-snapshot",
                project_id="p1",
                name="Kopuk",
                framework_profile_id="dodaf",
                framework_version="2.02",
                version="v0001",
                status=model.SNAPSHOT_DRAFT,
                created_at="2026-08-12T18:00:00+03:00",
                elements=(element,),
                relationships=(dangling,),
            )

    def test_snapshot_status_and_reference_integrity_gates(self):
        evidence = _evidence()
        element = _element("fren", "Fren Sistemi", "System", "SGD-001", evidence)
        with self.assertRaisesRegex(ValueError, "kanonik mimari öğe olamaz"):
            model.ArchitectureElement(
                identity_key="reddedilmis",
                framework_profile_id="dodaf",
                name="Reddedilmiş Öğe",
                element_type="System",
                description="Reddedilen aday kanonik koleksiyona giremez.",
                source_requirement_ids=("SGD-001",),
                evidence_text=evidence.evidence_text,
                confidence_score=0.8,
                evidence_links=(evidence,),
                review_status=model.REVIEW_REJECTED,
            )
        with self.assertRaisesRegex(ValueError, "'Uyumlu'"):
            model.ArchitectureSnapshot(
                identity_key="uyumlu-degil",
                project_id="p1",
                name="Doğrulanmamış Mimari",
                framework_profile_id="dodaf",
                framework_version="2.02",
                version="v0001",
                status=model.SNAPSHOT_CONFORMANT,
                created_at="2026-08-12T19:00:00+03:00",
                elements=(element,),
            )

        blocking = model.ValidationFinding(
            code="missing_required_data",
            severity="error",
            message="SV-1 zorunlu verisi eksik.",
            target_id=element.stable_id,
            view_id="SV-1",
            evidence_ids=(evidence.evidence_id,),
            blocking=False,
        )
        with self.assertRaisesRegex(ValueError, "Çerçeveyle hizalı"):
            model.ArchitectureSnapshot(
                identity_key="engelli",
                project_id="p1",
                name="Engelli Mimari",
                framework_profile_id="dodaf",
                framework_version="2.02",
                version="v0001",
                status=model.SNAPSHOT_ALIGNED,
                created_at="2026-08-12T19:00:00+03:00",
                elements=(element,),
                validation_findings=(blocking,),
                selected_view_ids=("SV-1",),
            )

        wrong_profile = model.CandidateProposal(
            identity_key="SGD-001-fren",
            framework_profile_id="naf",
            proposal_type="element",
            title="Yanlış profil adayı",
            rationale="Bütünlük testi",
            proposed_payload={
                "identity_key": "SGD-001-fren",
                "name": "Fren",
                "element_type": "System",
                "description": evidence.evidence_text,
            },
            payload_evidence_ids=_payload_evidence(
                evidence,
                "identity_key", "name", "element_type", "description",
            ),
            source_requirement_ids=("SGD-001",),
            evidence_text=evidence.evidence_text,
            confidence_score=0.7,
            evidence_links=(evidence,),
        )
        with self.assertRaisesRegex(ValueError, "Aday öneri snapshot profili"):
            model.ArchitectureSnapshot(
                identity_key="yanlis-profil",
                project_id="p1",
                name="Yanlış Profil",
                framework_profile_id="dodaf",
                framework_version="2.02",
                version="v0001",
                status=model.SNAPSHOT_DRAFT,
                created_at="2026-08-12T19:00:00+03:00",
                elements=(element,),
                candidate_proposals=(wrong_profile,),
            )

        proposal = model.CandidateProposal(
            identity_key="SGD-001-fren",
            framework_profile_id="dodaf",
            proposal_type="element",
            title="Çözülmemiş aday",
            rationale="Durum kapısı testi",
            proposed_payload={
                "identity_key": "SGD-001-fren",
                "name": "Fren",
                "element_type": "System",
                "description": evidence.evidence_text,
            },
            payload_evidence_ids=_payload_evidence(
                evidence,
                "identity_key", "name", "element_type", "description",
            ),
            source_requirement_ids=("SGD-001",),
            evidence_text=evidence.evidence_text,
            confidence_score=0.7,
            evidence_links=(evidence,),
        )
        with self.assertRaisesRegex(ValueError, "Çerçeveyle hizalı"):
            model.ArchitectureSnapshot(
                identity_key="cozulmemis",
                project_id="p1",
                name="Çözülmemiş Mimari",
                framework_profile_id="dodaf",
                framework_version="2.02",
                version="v0001",
                status=model.SNAPSHOT_ALIGNED,
                created_at="2026-08-12T19:00:00+03:00",
                elements=(element,),
                candidate_proposals=(proposal,),
                selected_view_ids=("SV-1",),
            )

        accept = model.ReviewDecision.for_proposal(
            proposal, model.DECISION_ACCEPT, "Mimar", "2026-08-12T19:01:00+03:00",
        )
        with self.assertRaisesRegex(ValueError, "Çerçeveyle hizalı"):
            model.ArchitectureSnapshot(
                identity_key="uygulanmamis-kabul",
                project_id="p1",
                name="Uygulanmamış Kabul",
                framework_profile_id="dodaf",
                framework_version="2.02",
                version="v0001",
                status=model.SNAPSHOT_ALIGNED,
                created_at="2026-08-12T19:02:00+03:00",
                elements=(element,),
                candidate_proposals=(proposal,),
                review_decisions=(accept,),
                selected_view_ids=("SV-1",),
            )
        reject = model.ReviewDecision.for_proposal(
            proposal, model.DECISION_REJECT, "Mimar", "2026-08-12T19:02:00+03:00",
        )
        with self.assertRaisesRegex(ValueError, "birden fazla etkin"):
            model.ArchitectureSnapshot(
                identity_key="celiskili-karar",
                project_id="p1",
                name="Çelişkili Karar",
                framework_profile_id="dodaf",
                framework_version="2.02",
                version="v0001",
                status=model.SNAPSHOT_DRAFT,
                created_at="2026-08-12T19:03:00+03:00",
                elements=(element,),
                candidate_proposals=(proposal,),
                review_decisions=(accept, reject),
            )

        stale_defer = model.ReviewDecision(
            candidate_id=proposal.proposal_id,
            decision=model.DECISION_DEFER,
            actor_type=model.ACTOR_MODEL,
            actor="Gemma",
            decided_at="2026-08-12T19:02:30+03:00",
            candidate_digest="0" * 64,
        )
        with self.assertRaisesRegex(ValueError, "onaydan sonra değişmiş"):
            model.ArchitectureSnapshot(
                identity_key="eski-ertele",
                project_id="p1",
                name="Eski Ertele Kaydı",
                framework_profile_id="dodaf",
                framework_version="2.02",
                version="v0001",
                status=model.SNAPSHOT_DRAFT,
                created_at="2026-08-12T19:03:00+03:00",
                elements=(element,),
                candidate_proposals=(proposal,),
                review_decisions=(stale_defer,),
            )

        orphan_finding = model.ValidationFinding(
            code="orphan",
            severity="error",
            message="Bilinmeyen hedef ve kanıt.",
            target_id="ARCH-ELEMENT-YOK",
            evidence_ids=("EVIDENCE-YOK",),
        )
        with self.assertRaisesRegex(ValueError, "bulgusu hedefi"):
            model.ArchitectureSnapshot(
                identity_key="orphan-finding",
                project_id="p1",
                name="Yetim Bulgu",
                framework_profile_id="dodaf",
                framework_version="2.02",
                version="v0001",
                status=model.SNAPSHOT_DRAFT,
                created_at="2026-08-12T19:04:00+03:00",
                elements=(element,),
                validation_findings=(orphan_finding,),
            )

    def test_strict_json_identity_version_time_and_boolean_contracts(self):
        with self.assertRaisesRegex(ValueError, "çakışıyor"):
            model.stable_id_for("X", {"A": 1, "a": 2})
        with self.assertRaisesRegex(ValueError, "Desteklenmeyen kimlik"):
            model.stable_id_for("X", object())

        evidence = _evidence()
        with self.assertRaisesRegex(ValueError, "JSON nesnesi anahtarları"):
            model.CandidateProposal(
                identity_key="json-key",
                framework_profile_id="dodaf",
                proposal_type="element",
                title="Geçersiz JSON anahtarı",
                rationale="Bütünlük testi",
                proposed_payload={1: "değer"},
                source_requirement_ids=("SGD-001",),
                evidence_text=evidence.evidence_text,
                confidence_score=0.7,
                evidence_links=(evidence,),
            )
        with self.assertRaisesRegex(ValueError, "boolean"):
            model.ValidationFinding(
                code="bad_bool",
                severity="error",
                message="Boolean alanı yanlış.",
                blocking="false",
            )
        with self.assertRaisesRegex(ValueError, "vNNNN"):
            model.ValidationFinding(
                code="bad_version",
                severity="error",
                message="Sürüm yanlış.",
                version="1",
            )
        with self.assertRaisesRegex(ValueError, "saat dilimi"):
            model.ArchitectureSnapshot(
                identity_key="bad-time",
                project_id="p1",
                name="Zamanı Hatalı",
                framework_profile_id="dodaf",
                framework_version="2.02",
                version="v0001",
                status=model.SNAPSHOT_DRAFT,
                created_at="2026-08-12T19:00:00",
            )

    def test_profile_rejects_casefold_duplicate_views_and_partial_application_profile(self):
        view = model.ViewDefinition(
            framework_profile_id="test",
            framework_version="1.0",
            view_id="V-1",
            name="View",
            purpose="Amaç",
            required_element_types=(),
            required_relationships=(),
            data_prerequisites=("Kanıt",),
            export_type="diagram",
            package="test",
        )
        lower = model.ViewDefinition(
            framework_profile_id="test",
            framework_version="1.0",
            view_id="v-1",
            name="Aynı View",
            purpose="Amaç",
            required_element_types=(),
            required_relationships=(),
            data_prerequisites=("Kanıt",),
            export_type="diagram",
            package="test",
        )
        with self.assertRaisesRegex(ValueError, "yinelenen görünüm"):
            model.FrameworkProfile(
                profile_id="test",
                name="Test",
                version="1.0",
                description="Test profili",
                view_definitions=(view, lower),
            )
        with self.assertRaisesRegex(ValueError, "birlikte"):
            model.FrameworkProfile(
                profile_id="test",
                name="Test",
                version="1.0",
                description="Test profili",
                view_definitions=(view,),
                default_application_profile="ArchiMate",
            )


if __name__ == "__main__":
    unittest.main()
