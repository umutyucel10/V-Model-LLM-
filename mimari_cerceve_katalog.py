# -*- coding: utf-8 -*-
"""DoDAF 2.02 ve NAF 4.1 için değiştirilemez EHSİM görünüm kataloğu.

``required_element_types`` ve ``required_relationships`` alanları Kart 1'de
uygulanacak **EHSİM asgari veri kapılarıdır**. Eksiksiz DM2/PES veya NAF
Information Model eşlemesi oldukları iddia edilmez. ``export_type`` gerçekleşmiş
bir dosya dışa aktarıcısı değil, görünümün sunum ailesidir. Exchange hedefleri
planlanan hedef olarak kaydedilmiştir; doğrulayıcılar henüz belirsiz/eksiktir.

Katalog UI modüllerine bağlı değildir ve NAF v3 adlarını kanonik kayıt olarak
içermez.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping

from mimari_cerceve_model import FrameworkProfile, ViewDefinition


DODAF_PROFILE_ID = "dodaf"
DODAF_VERSION = "2.02"
NAF_PROFILE_ID = "naf"
NAF_VERSION = "4.1"
ARCHIMATE_PROFILE = "ArchiMate"
ARCHIMATE_VERSION = "3.2"

DODAF_INITIAL_PACKAGE = "dodaf_initial"
DODAF_SERVICE_PACKAGE = "dodaf_service_phase_2"
NAF_INITIAL_PACKAGE = "naf_initial"

DODAF_INITIAL_VIEW_IDS = (
    "AV-1", "AV-2", "SV-1", "SV-2", "SV-4", "SV-5a", "SV-7",
)
DODAF_SERVICE_VIEW_IDS = (
    "SvcV-1", "SvcV-2", "SvcV-4", "SvcV-5", "SvcV-7",
)
NAF_INITIAL_VIEW_IDS = (
    "L2-L3", "L3", "L4", "L8", "P2", "P3", "P4", "L4-P4", "P8",
)

DODAF_ALL_SOURCE = (
    "https://dodcio.defense.gov/Library/DoD-Architecture-Framework/"
    "dodaf20_all_view/"
)
DODAF_SYSTEMS_SOURCE = (
    "https://dodcio.defense.gov/Library/DoD-Architecture-Framework/"
    "dodaf20_systems/"
)
DODAF_SERVICES_SOURCE = (
    "https://dodcio.defense.gov/Library/DoD-Architecture-Framework/"
    "dodaf20_services/"
)
NAF_SOURCE = (
    "https://www.nato.int/content/dam/nato/webready/documents/"
    "publications-and-reports/NATO-Architecture-Framework-v4-1-en.pdf"
)
NAF_ARCHIMATE_SOURCE = (
    "https://www.nato.int/content/dam/nato/webready/documents/"
    "publications-and-reports/NATO-Architecture-Framework-ArchiMate-v4-1-en.pdf"
)


def _view(
    profile_id: str,
    version: str,
    view_id: str,
    name: str,
    purpose: str,
    required_elements: tuple[str, ...],
    required_relationships: tuple[str, ...],
    prerequisites: tuple[str, ...],
    export_type: str,
    package: str,
    source_url: str,
    *,
    required_any_of_elements: tuple[tuple[str, ...], ...] = (),
    required_any_of_relationships: tuple[tuple[str, ...], ...] = (),
    optional_elements: tuple[str, ...] = (),
    optional_relationships: tuple[str, ...] = (),
    generation_classes: tuple[str, ...] = ("A", "B", "C"),
    exchange_target: str,
    notes: str = "",
) -> ViewDefinition:
    return ViewDefinition(
        framework_profile_id=profile_id,
        framework_version=version,
        view_id=view_id,
        name=name,
        purpose=purpose,
        required_element_types=required_elements,
        required_relationships=required_relationships,
        data_prerequisites=prerequisites,
        export_type=export_type,
        package=package,
        required_any_of_element_types=required_any_of_elements,
        required_any_of_relationships=required_any_of_relationships,
        optional_element_types=optional_elements,
        optional_relationships=optional_relationships,
        generation_classes=generation_classes,
        exchange_target=exchange_target,
        implementation_status="catalog_only",
        source_url=source_url,
        notes=notes,
    )


_DODAF_EXCHANGE = "PES — planlanan; şema/doğrulayıcı belirsiz/eksik"
_NAF_EXCHANGE = "ArchiMate 3.2 — planlanan; exchange doğrulayıcı belirsiz/eksik"


DODAF_INITIAL_VIEWS = (
    _view(
        DODAF_PROFILE_ID, DODAF_VERSION, "AV-1",
        "Overview and Summary Information",
        "Mimari açıklamanın kapsam, amaç, bağlam, durum, varsayım ve kısıtlarını yönetici düzeyinde özetlemek.",
        ("ArchitectureDescription", "ArchitectureMetadata"),
        (),
        (
            "Mimari açıklama kimliği ve geliştiren kurum/rol kanıtı",
            "Kapsam ve seçilen viewpoint/model listesi",
            "Amaç, perspektif, bağlam ve karar ihtiyacı",
            "Zaman ufku, mimari durum, varsayımlar ve kısıtlar",
            "Kullanılan yetkili kaynaklar",
        ),
        "structured_text", DODAF_INITIAL_PACKAGE, DODAF_ALL_SOURCE,
        exchange_target=_DODAF_EXCHANGE,
        notes="AV-1 için yapay grafik ilişkisi zorunlu tutulmaz.",
    ),
    _view(
        DODAF_PROFILE_ID, DODAF_VERSION, "AV-2",
        "Integrated Dictionary",
        "Mimari açıklamada kullanılan terim, tanım ve yetkili kaynakları ortak bir sözlükte toplamak.",
        ("DictionaryTerm", "Definition", "AuthoritativeSource"),
        ("defined_by", "derived_from"),
        (
            "Her terim için kararlı kimlik",
            "Boş olmayan tanım",
            "Tanımın yetkili kaynak referansı",
        ),
        "dictionary", DODAF_INITIAL_PACKAGE, DODAF_ALL_SOURCE,
        optional_relationships=("parent_of",),
        generation_classes=("A", "B"), exchange_target=_DODAF_EXCHANGE,
        notes="Taksonomi hiyerarşisi yalnızca kaynakta varsa eklenir.",
    ),
    _view(
        DODAF_PROFILE_ID, DODAF_VERSION, "SV-1",
        "Systems Interface Description",
        "Sistemleri, sistem öğelerini ve aralarındaki bağlantıları tanımlamak.",
        ("System", "SystemResourceFlow"),
        ("flow_source", "flow_target"),
        (
            "En az iki kanıtlı sistem/bağlantı ucu",
            "Uçlar arasında kanıtlı kaynak akışı veya bağlantı",
        ),
        "diagram", DODAF_INITIAL_PACKAGE, DODAF_SYSTEMS_SOURCE,
        optional_elements=("SystemItem", "Organization", "PersonType"),
        optional_relationships=("contains", "part_of"),
        exchange_target=_DODAF_EXCHANGE,
    ),
    _view(
        DODAF_PROFILE_ID, DODAF_VERSION, "SV-2",
        "Systems Resource Flow Description",
        "Sistemler arası kaynak akışlarını ve bunları gerçekleştiren bağlantı ayrıntılarını tanımlamak.",
        ("System", "Port", "SystemResourceFlow"),
        ("port_belongs_to", "flow_source", "flow_target"),
        (
            "Kaynak ve hedef sistem/port kimlikleri",
            "Akış yönü ve taşınan kaynak tanımı",
            "Protokol belirtilmişse yetkili standart kaynağı",
        ),
        "diagram", DODAF_INITIAL_PACKAGE, DODAF_SYSTEMS_SOURCE,
        optional_elements=("Protocol", "Standard"),
        optional_relationships=("conforms_to", "implements"),
        exchange_target=_DODAF_EXCHANGE,
    ),
    _view(
        DODAF_PROFILE_ID, DODAF_VERSION, "SV-4",
        "Systems Functionality Description",
        "Sistemlerin gerçekleştirdiği fonksiyonları, fonksiyon tahsislerini ve fonksiyonlar arası kaynak akışlarını tanımlamak.",
        ("SystemFunction", "SystemOrResource", "ResourceFlow"),
        ("performed_by", "flow_source", "flow_target"),
        (
            "Kanıtlı sistem fonksiyonu",
            "Fonksiyonu gerçekleştiren sistem/kaynak tahsisi",
            "Fonksiyonun kanıtlı girdi/çıktı akışları",
        ),
        "diagram", DODAF_INITIAL_PACKAGE, DODAF_SYSTEMS_SOURCE,
        optional_relationships=("allocated_to", "decomposes"),
        exchange_target=_DODAF_EXCHANGE,
    ),
    _view(
        DODAF_PROFILE_ID, DODAF_VERSION, "SV-5a",
        "Operational Activity to Systems Function Traceability Matrix",
        "Operasyonel faaliyetleri sistem fonksiyonlarına çoktan-çoğa izlenebilir biçimde eşlemek.",
        ("OperationalActivity", "SystemFunction"),
        ("maps_to",),
        (
            "Operasyonel faaliyet ve sistem fonksiyonunun gerçek kimlikleri",
            "Her eşleme için kaynak kanıtı veya açık kullanıcı onayı",
        ),
        "matrix", DODAF_INITIAL_PACKAGE, DODAF_SYSTEMS_SOURCE,
        optional_relationships=("realizes",),
        exchange_target=_DODAF_EXCHANGE,
    ),
    _view(
        DODAF_PROFILE_ID, DODAF_VERSION, "SV-7",
        "Systems Measures Matrix",
        "Sistem modeli öğelerinin ilgili zaman ufkundaki nitel veya nicel ölçütlerini tanımlamak.",
        ("SystemModelElement", "Measure", "Timeframe"),
        ("measure_applies_to", "valid_during"),
        (
            "Ölçüt adı ve hedef/değer",
            "Nicel ölçüt için birim",
            "Ölçütün uygulandığı sistem modeli öğesi",
            "Geçerli zaman ufku veya mimari faz",
        ),
        "table", DODAF_INITIAL_PACKAGE, DODAF_SYSTEMS_SOURCE,
        exchange_target=_DODAF_EXCHANGE,
    ),
)


DODAF_SERVICE_VIEWS = (
    _view(
        DODAF_PROFILE_ID, DODAF_VERSION, "SvcV-1",
        "Services Context Description",
        "Servisleri, servis öğelerini ve aralarındaki bağlantıları tanımlamak.",
        ("Service", "ServiceResourceFlow"),
        ("flow_source", "flow_target"),
        ("Kanıtlı servis sınırları ve uçları", "Servisler arası kanıtlı bağlantı/akış"),
        "diagram", DODAF_SERVICE_PACKAGE, DODAF_SERVICES_SOURCE,
        optional_elements=("SubService", "Organization", "PersonType"),
        optional_relationships=("part_of",), exchange_target=_DODAF_EXCHANGE,
    ),
    _view(
        DODAF_PROFILE_ID, DODAF_VERSION, "SvcV-2",
        "Services Resource Flow Description",
        "Servisler arası kaynak akışlarının uç, yön ve bağlantı ayrıntılarını tanımlamak.",
        ("Service", "Port", "ServiceResourceFlow"),
        ("port_belongs_to", "flow_source", "flow_target"),
        (
            "Üreten ve tüketen servis/port kimlikleri",
            "Akış yönü ve taşınan kaynak",
            "Protokol belirtilmişse yetkili standart kaynağı",
        ),
        "diagram", DODAF_SERVICE_PACKAGE, DODAF_SERVICES_SOURCE,
        optional_elements=("Protocol", "Standard"),
        optional_relationships=("conforms_to", "implements"),
        exchange_target=_DODAF_EXCHANGE,
    ),
    _view(
        DODAF_PROFILE_ID, DODAF_VERSION, "SvcV-4",
        "Services Functionality Description",
        "Servis fonksiyonlarını, bunların servis/kaynak tahsislerini ve veri akışlarını tanımlamak.",
        ("ServiceFunction", "ServiceOrResource", "ResourceFlow"),
        ("performed_by", "flow_source", "flow_target"),
        (
            "Kanıtlı servis fonksiyonu",
            "Fonksiyonun servis/kaynak tahsisi",
            "Kanıtlı girdi ve çıktı akışları",
        ),
        "diagram", DODAF_SERVICE_PACKAGE, DODAF_SERVICES_SOURCE,
        optional_relationships=("allocated_to", "decomposes"),
        exchange_target=_DODAF_EXCHANGE,
    ),
    _view(
        DODAF_PROFILE_ID, DODAF_VERSION, "SvcV-5",
        "Operational Activity to Services Traceability Matrix",
        "Operasyonel faaliyetleri servis fonksiyonlarına izlenebilir biçimde eşlemek.",
        ("OperationalActivity", "ServiceFunction"),
        ("maps_to",),
        (
            "Operasyonel faaliyet ve servis fonksiyonunun gerçek kimlikleri",
            "Eşleme için kaynak kanıtı veya açık kullanıcı onayı",
        ),
        "matrix", DODAF_SERVICE_PACKAGE, DODAF_SERVICES_SOURCE,
        optional_relationships=("realizes",), exchange_target=_DODAF_EXCHANGE,
    ),
    _view(
        DODAF_PROFILE_ID, DODAF_VERSION, "SvcV-7",
        "Services Measures Matrix",
        "Servis modeli öğelerinin ilgili zaman ufkundaki ölçütlerini tanımlamak.",
        ("ServiceModelElement", "Measure", "Timeframe"),
        ("measure_applies_to", "valid_during"),
        (
            "Servis ölçütü ve hedef/değer",
            "Nicel ölçüt için birim",
            "Hedef servis modeli öğesi",
            "Geçerli zaman ufku",
        ),
        "table", DODAF_SERVICE_PACKAGE, DODAF_SERVICES_SOURCE,
        exchange_target=_DODAF_EXCHANGE,
    ),
)


NAF_INITIAL_VIEWS = (
    _view(
        NAF_PROFILE_ID, NAF_VERSION, "L2-L3", "Logical Concept",
        "Mimari bağlamı ve mantıksal kavramı paydaşlar için zengin resim olarak anlatmak.",
        (), (),
        ("Kaynak kanıtına bağlı kavramsal bağlam ve anlatılacak kaygı",),
        "diagram", NAF_INITIAL_PACKAGE, NAF_SOURCE,
        optional_elements=("Node", "Needline"),
        exchange_target=_NAF_EXCHANGE,
        notes=(
            "NAF 4.1 L2-L3 çoğunlukla rich picture'dır; resmî kesit zorunlu "
            "bilgi modeli öğesi veya adlandırılmış ilişki göstermez. Node/Needline "
            "yalnız EHSİM'in yapılandırılmış varyantında kullanılabilir."
        ),
    ),
    _view(
        NAF_PROFILE_ID, NAF_VERSION, "L3", "Logical Interactions",
        "Mantıksal aktif kaynaklar arasındaki ilgili etkileşimleri ve taşınan pasif kaynakları tanımlamak.",
        ("LogicalActiveResource", "LogicalInteraction", "LogicalPassiveResource"),
        ("interaction_source", "interaction_target", "conveys"),
        (
            "İki kanıtlı mantıksal aktif uç",
            "Uçlar arası mantıksal etkileşim",
            "Etkileşimin taşıdığı mantıksal pasif kaynak",
        ),
        "diagram", NAF_INITIAL_PACKAGE, NAF_SOURCE,
        optional_elements=("Node", "Needline"),
        exchange_target=_NAF_EXCHANGE,
    ),
    _view(
        NAF_PROFILE_ID, NAF_VERSION, "L4", "Logical Activities",
        "Mantıksal faaliyetleri, gruplama/bileşimlerini ve faaliyetler arası mantıksal akışları tanımlamak.",
        ("OperationalActivity", "OperationalControlFlow"),
        ("control_flow_source", "control_flow_target", "performs"),
        (
            "Kanıtlı operasyonel faaliyetler ve kontrol akışları",
            "Her faaliyet için en az bir Node veya Role icracısı",
        ),
        "diagram", NAF_INITIAL_PACKAGE, NAF_SOURCE,
        required_any_of_elements=(("Node", "Role"),),
        optional_elements=("LogicalEvent", "LogicalPassiveResource"),
        optional_relationships=("triggers", "operational_flow"),
        exchange_target=_NAF_EXCHANGE,
    ),
    _view(
        NAF_PROFILE_ID, NAF_VERSION, "L8", "Logical Constraints",
        "Mantıksal kısıtları, mantıksal gereksinimleri ve bunların uygulandığı öğeleri tanımlamak.",
        ("LogicalRequirement", "LogicalConstraint"),
        ("relates_to", "applies_to"),
        (
            "Mantıksal gereksinim ve ilgili mantıksal kısıt",
            "En az bir ilgili hedef: LogicalActiveResource, LogicalBehaviour veya LogicalPassiveResource",
        ),
        "structured_text", NAF_INITIAL_PACKAGE, NAF_SOURCE,
        required_any_of_elements=((
            "LogicalActiveResource", "LogicalBehaviour", "LogicalPassiveResource",
        ),),
        optional_elements=("LogicalSpecification", "LogicalRationale"),
        optional_relationships=("originates_from", "aggregates"),
        generation_classes=("A", "B"), exchange_target=_NAF_EXCHANGE,
    ),
    _view(
        NAF_PROFILE_ID, NAF_VERSION, "P2", "Resource Structure",
        "Fiziksel aktif/pasif kaynakların yapısını, yetenek konfigürasyonlarını ve bağımlılıklarını tanımlamak.",
        ("CapabilityConfiguration", "PhysicalActiveResource", "PhysicalPassiveResource"),
        ("aggregates", "depends_on"),
        (
            "Kanıtlı yetenek konfigürasyonu",
            "Fiziksel aktif ve pasif kaynaklar",
            "Kaynak yapısı ve kaynaklar arası bağımlılıklar",
        ),
        "diagram", NAF_INITIAL_PACKAGE, NAF_SOURCE,
        optional_relationships=("structurally_contains",), exchange_target=_NAF_EXCHANGE,
    ),
    _view(
        NAF_PROFILE_ID, NAF_VERSION, "P3", "Resource Interactions",
        "Aktif kaynaklar arasındaki etkileşimleri, uygulanan protokolleri ve standart bağlarını tanımlamak.",
        ("PhysicalActiveResource", "ResourceInteraction", "Protocol", "Standard"),
        ("interaction_source", "interaction_target", "implements", "conforms_to"),
        (
            "İki kanıtlı fiziksel aktif kaynak ucu",
            "Uçlar arası kaynak etkileşimi",
            "Uygulanan protokol, ilgili standart ve uygulayan kaynaklar",
        ),
        "diagram", NAF_INITIAL_PACKAGE, NAF_SOURCE,
        optional_elements=("PhysicalPassiveResource", "LogicalInteraction"),
        optional_relationships=("conveys", "realizes"), exchange_target=_NAF_EXCHANGE,
    ),
    _view(
        NAF_PROFILE_ID, NAF_VERSION, "P4", "Resource Functions",
        "Kaynak fonksiyonlarını, bunları gerçekleştiren kaynakları ve fonksiyon/kaynak akışlarını tanımlamak.",
        ("ResourceFunction", "PhysicalActiveResource", "PhysicalPassiveResource", "FunctionalFlow", "ResourceFlow"),
        ("flow_source", "flow_target"),
        (
            "Kaynak fonksiyonu ve onu kullanan/gerçekleştiren fiziksel aktif kaynak",
            "Fonksiyonun kullandığı veya teslim ettiği fiziksel pasif kaynak",
            "Fonksiyonel akışlar ve kaynak akışları",
        ),
        "diagram", NAF_INITIAL_PACKAGE, NAF_SOURCE,
        required_any_of_relationships=(
            ("uses", "performs"),
            ("uses", "delivers"),
        ),
        optional_elements=("OperationalActivity", "ServiceFunction", "LogicalFunction"),
        optional_relationships=("realizes", "aggregates"), exchange_target=_NAF_EXCHANGE,
        notes=(
            "İlk alternatif grup aktif kaynak-fonksiyon; ikinci grup "
            "fonksiyon-pasif kaynak yönünde değerlendirilir."
        ),
    ),
    _view(
        NAF_PROFILE_ID, NAF_VERSION, "L4-P4", "Activity to Function Mapping",
        "Operasyonel faaliyetler ile kaynak fonksiyonları arasındaki izlenebilirliği tanımlamak.",
        ("OperationalActivity", "ResourceFunction"),
        ("realizes",),
        (
            "Operasyonel faaliyet ve kaynak fonksiyonunun gerçek kimlikleri",
            "Her eşleme için kaynak kanıtı veya açık kullanıcı onayı",
        ),
        "matrix", NAF_INITIAL_PACKAGE, NAF_SOURCE,
        optional_elements=("ServiceFunction", "PhysicalActiveResource"),
        optional_relationships=("maps_to", "performs", "uses"),
        exchange_target=_NAF_EXCHANGE,
    ),
    _view(
        NAF_PROFILE_ID, NAF_VERSION, "P8", "Resource Constraints",
        "Kaynak kısıtlarını, kaynak gereksinimlerini ve bunların uygulandığı fiziksel öğeleri tanımlamak.",
        ("ResourceRequirement", "ResourceConstraint"),
        ("relates_to", "applies_to"),
        (
            "Kaynak gereksinimi ve ilgili kaynak kısıtı",
            "En az bir ilgili hedef: PhysicalActiveResource, PhysicalBehaviour veya PhysicalPassiveResource",
        ),
        "structured_text", NAF_INITIAL_PACKAGE, NAF_SOURCE,
        required_any_of_elements=((
            "PhysicalActiveResource", "PhysicalBehaviour", "PhysicalPassiveResource",
        ),),
        optional_elements=("ResourceSpecification", "ResourceRationale"),
        optional_relationships=("originates_from", "aggregates"),
        generation_classes=("A", "B"), exchange_target=_NAF_EXCHANGE,
    ),
)


DODAF_PROFILE = FrameworkProfile(
    profile_id=DODAF_PROFILE_ID,
    name="Department of Defense Architecture Framework",
    version=DODAF_VERSION,
    description=(
        "DoDAF 2.02 için EHSİM ilk sistem paketi ve ikinci aşama servis "
        "paketi. Katalog tek başına DM2/PES uyumu kanıtlamaz."
    ),
    view_definitions=(*DODAF_INITIAL_VIEWS, *DODAF_SERVICE_VIEWS),
    exchange_target=_DODAF_EXCHANGE,
    source_url="https://dodcio.defense.gov/DoDAF/",
)

NAF_PROFILE = FrameworkProfile(
    profile_id=NAF_PROFILE_ID,
    name="NATO Architecture Framework",
    version=NAF_VERSION,
    description=(
        "NAF 4.1 ilk EHSİM viewpoint paketi. ArchiMate 3.2 NATO'nun tek "
        "varsayılanı değil, EHSİM'in varsayılan uygulama profilidir."
    ),
    view_definitions=NAF_INITIAL_VIEWS,
    default_application_profile=ARCHIMATE_PROFILE,
    application_profile_version=ARCHIMATE_VERSION,
    exchange_target=_NAF_EXCHANGE,
    source_url=NAF_SOURCE,
)


FRAMEWORK_PROFILES: Mapping[str, FrameworkProfile] = MappingProxyType({
    DODAF_PROFILE_ID: DODAF_PROFILE,
    NAF_PROFILE_ID: NAF_PROFILE,
})

VIEW_CATALOG: Mapping[tuple[str, str], ViewDefinition] = MappingProxyType({
    (profile.profile_id, view.view_id): view
    for profile in FRAMEWORK_PROFILES.values()
    for view in profile.view_definitions
})

PACKAGE_CATALOG: Mapping[str, tuple[ViewDefinition, ...]] = MappingProxyType({
    DODAF_INITIAL_PACKAGE: DODAF_INITIAL_VIEWS,
    DODAF_SERVICE_PACKAGE: DODAF_SERVICE_VIEWS,
    NAF_INITIAL_PACKAGE: NAF_INITIAL_VIEWS,
})


def _profile_key(value: str) -> str:
    key = " ".join(str(value or "").split()).casefold()
    aliases = {
        "dodaf": DODAF_PROFILE_ID,
        "dodaf 2.02": DODAF_PROFILE_ID,
        "dodaf-2.02": DODAF_PROFILE_ID,
        "naf": NAF_PROFILE_ID,
        "naf 4.1": NAF_PROFILE_ID,
        "naf-4.1": NAF_PROFILE_ID,
    }
    try:
        return aliases[key]
    except KeyError as error:
        raise KeyError(f"Mimari çerçeve profili bulunamadı: {value}") from error


def get_framework_profile(profile_id: str) -> FrameworkProfile:
    return FRAMEWORK_PROFILES[_profile_key(profile_id)]


def get_view_definition(profile_id: str, view_id: str) -> ViewDefinition:
    profile = get_framework_profile(profile_id)
    return profile.get_view(view_id)


def get_view_package(package: str) -> tuple[ViewDefinition, ...]:
    try:
        return PACKAGE_CATALOG[str(package)]
    except KeyError as error:
        raise KeyError(f"Mimari görünüm paketi bulunamadı: {package}") from error


def list_view_definitions(profile_id: str | None = None) -> tuple[ViewDefinition, ...]:
    if profile_id is None:
        return tuple(
            view
            for profile in FRAMEWORK_PROFILES.values()
            for view in profile.view_definitions
        )
    return get_framework_profile(profile_id).view_definitions


__all__ = [
    "ARCHIMATE_PROFILE", "ARCHIMATE_VERSION", "DODAF_INITIAL_PACKAGE",
    "DODAF_INITIAL_VIEW_IDS", "DODAF_INITIAL_VIEWS", "DODAF_PROFILE",
    "DODAF_PROFILE_ID", "DODAF_SERVICE_PACKAGE", "DODAF_SERVICE_VIEW_IDS",
    "DODAF_SERVICE_VIEWS", "DODAF_VERSION", "FRAMEWORK_PROFILES",
    "NAF_INITIAL_PACKAGE", "NAF_INITIAL_VIEW_IDS", "NAF_INITIAL_VIEWS",
    "NAF_PROFILE", "NAF_PROFILE_ID", "NAF_VERSION", "PACKAGE_CATALOG",
    "VIEW_CATALOG", "get_framework_profile", "get_view_definition",
    "get_view_package", "list_view_definitions",
]
