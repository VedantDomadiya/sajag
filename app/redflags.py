"""The red-flag taxonomy: codes, weights, keyword rules and plain-language explanations.

Gemini is the primary detector. These keyword rules are a second, deterministic opinion that runs on both the
original-script transcript and Gemini's English translation, so a flag is still caught if the model under-reports it.
Rules can only raise the alarm when the model also finds the call at least suspicious (see risk.py).
"""

import re

AUTHORITY = "AUTHORITY"
ARREST_THREAT = "ARREST_THREAT"
URGENCY = "URGENCY"
SECRECY = "SECRECY"
OTP_REQUEST = "OTP_REQUEST"
MONEY_REQUEST = "MONEY_REQUEST"
REMOTE_ACCESS = "REMOTE_ACCESS"

CODES = [AUTHORITY, ARREST_THREAT, URGENCY, SECRECY, OTP_REQUEST, MONEY_REQUEST, REMOTE_ACCESS]

# How much each distinct flag adds to the rule score (capped at 100).
WEIGHTS = {
    AUTHORITY: 20,
    ARREST_THREAT: 35,
    URGENCY: 15,
    SECRECY: 30,
    OTP_REQUEST: 40,
    MONEY_REQUEST: 35,
    REMOTE_ACCESS: 35,
}

# Short labels for the UI chips.
LABELS = {
    AUTHORITY: {"en": "Claims to be police / bank", "hi": "पुलिस / बैंक होने का दावा", "gu": "પોલીસ / બેંક હોવાનો દાવો"},
    ARREST_THREAT: {"en": "Threat of arrest", "hi": "गिरफ़्तारी की धमकी", "gu": "ધરપકડની ધમકી"},
    URGENCY: {"en": "Rushing you", "hi": "जल्दबाज़ी", "gu": "ઉતાવળ કરાવે છે"},
    SECRECY: {"en": "Keep it secret", "hi": "किसी को मत बताओ", "gu": "કોઈને ના કહો"},
    OTP_REQUEST: {"en": "Asks for OTP / PIN", "hi": "OTP / PIN माँगा", "gu": "OTP / PIN માંગ્યો"},
    MONEY_REQUEST: {"en": "Asks for money", "hi": "पैसे माँगे", "gu": "પૈસા માંગ્યા"},
    REMOTE_ACCESS: {"en": "Install app / share screen", "hi": "ऐप / स्क्रीन शेयर", "gu": "એપ / સ્ક્રીન શેર"},
}

# One simple, true sentence per flag: the "why" an elder hears and reads.
EXPLAIN = {
    AUTHORITY: {
        "en": "Real police, CBI, banks or RBI never ask for money or an OTP over a phone call.",
        "hi": "असली पुलिस, CBI, बैंक या RBI फ़ोन पर कभी पैसे या OTP नहीं माँगते।",
        "gu": "સાચી પોલીસ, CBI, બેંક કે RBI ક્યારેય ફોન પર પૈસા કે OTP માંગતા નથી.",
    },
    ARREST_THREAT: {
        "en": "Police never arrest anyone over a phone or video call. There is no such thing as a 'digital arrest'.",
        "hi": "पुलिस कभी फ़ोन या वीडियो कॉल पर किसी को गिरफ़्तार नहीं करती। 'डिजिटल अरेस्ट' जैसी कोई चीज़ नहीं होती।",
        "gu": "પોલીસ ક્યારેય ફોન કે વિડિયો કૉલ પર કોઈની ધરપકડ કરતી નથી. 'ડિજિટલ અરેસ્ટ' જેવું કંઈ હોતું જ નથી.",
    },
    URGENCY: {
        "en": "They are rushing you so you cannot think. Real officials always give you time.",
        "hi": "वे आपको जल्दबाज़ी में डाल रहे हैं ताकि आप सोच न सकें। असली अधिकारी हमेशा समय देते हैं।",
        "gu": "તેઓ તમને ઉતાવળ કરાવે છે જેથી તમે વિચારી ન શકો. સાચા અધિકારીઓ હંમેશા સમય આપે છે.",
    },
    SECRECY: {
        "en": "They told you to keep it secret. A real officer never asks you to hide anything from your family.",
        "hi": "उन्होंने कहा कि किसी को मत बताओ। असली अधिकारी कभी घर वालों से कुछ छिपाने को नहीं कहते।",
        "gu": "તેમણે કહ્યું કે કોઈને ના કહેશો. સાચા અધિકારી ક્યારેય ઘરનાથી કંઈ છુપાવવાનું કહેતા નથી.",
    },
    OTP_REQUEST: {
        "en": "Never tell anyone your OTP, PIN or CVV on a call, not even someone who says they are from the bank.",
        "hi": "OTP, PIN या CVV फ़ोन पर किसी को मत बताइए, बैंक वाले को भी नहीं।",
        "gu": "OTP, PIN કે CVV ફોન પર કોઈને પણ ના કહો, બેંકવાળાને પણ નહીં.",
    },
    MONEY_REQUEST: {
        "en": "No government office asks you to transfer money to 'verify' or 'clear' your name.",
        "hi": "कोई भी सरकारी दफ़्तर नाम साफ़ करने या 'वेरिफ़िकेशन' के लिए पैसे ट्रांसफ़र करने को नहीं कहता।",
        "gu": "કોઈ સરકારી કચેરી નામ સાફ કરવા કે 'વેરિફિકેશન' માટે પૈસા ટ્રાન્સફર કરવાનું કહેતી નથી.",
    },
    REMOTE_ACCESS: {
        "en": "Apps like AnyDesk or screen sharing hand your phone and bank to the caller. Never install them for a stranger.",
        "hi": "AnyDesk या स्क्रीन शेयर जैसे ऐप से सामने वाला आपके फ़ोन और बैंक पर क़ब्ज़ा कर लेता है। अजनबी के कहने पर कभी इंस्टॉल मत कीजिए।",
        "gu": "AnyDesk કે સ્ક્રીન શેર જેવી એપથી સામેવાળો તમારા ફોન અને બેંક પર કબજો કરી લે છે. અજાણ્યાના કહેવાથી ક્યારેય ઇન્સ્ટોલ ના કરો.",
    },
}

HEADLINES = {
    "SCAM": {
        "en": "Warning! This is a scam call. Hang up now.",
        "hi": "सावधान! यह फ़्रॉड कॉल है। फ़ोन काट दीजिए।",
        "gu": "સાવધાન! આ ફ્રોડ કૉલ છે. ફોન કાપી નાખો.",
    },
    "CAUTION": {
        "en": "Careful. This call looks suspicious. Do not share anything.",
        "hi": "ध्यान दीजिए। यह कॉल संदिग्ध लग रहा है। कुछ भी मत बताइए।",
        "gu": "ધ્યાન રાખો. આ કૉલ શંકાસ્પદ લાગે છે. કંઈ પણ ના કહેશો.",
    },
    "SAFE": {
        "en": "No danger signs on this call so far.",
        "hi": "इस कॉल में अभी तक कोई ख़तरा नहीं दिखा।",
        "gu": "આ કૉલમાં હજી સુધી કોઈ ખતરો દેખાતો નથી.",
    },
}

# Keyword rules. Each pattern is matched case-insensitively against the original transcript and the English gloss.
# Keep them specific: bare words like "payment", "hurry" or "link" appear in perfectly normal calls.
_RULES = {
    AUTHORITY: [
        r"\bpolice\b", r"\bcbi\b", r"cyber ?crime", r"\bcustoms?\b", r"\brbi\b", r"reserve bank", r"\binspector\b",
        r"narcotics", r"enforcement directorate", r"\btrai\b", r"kyc (department|section|team)",
        "पुलिस", "सीबीआई", "साइबर क्राइम", "कस्टम", "इंस्पेक्टर", "आरबीआई",
        "પોલીસ", "સાયબર", "કસ્ટમ", "ઇન્સ્પેક્ટર", "બેંકમાંથી", "બેંકના",
    ],
    ARREST_THREAT: [
        r"\barrest", r"\bwarrant\b", r"\bjail\b", r"money laundering", r"\bdrugs\b", r"case (has been |is )?(registered|filed)",
        r"\bfir\b", "गिरफ़्तार", "गिरफ्तार", "अरेस्ट", "वारंट", "जेल", "मनी लॉन्ड्रिंग", "ड्रग्स",
        "ધરપકડ", "અરેસ્ટ", "વોરંટ", "જેલ", "મની લોન્ડરિંગ", "ડ્રગ્સ",
    ],
    URGENCY: [
        r"\bimmediately\b", r"within (an? |one )?(hour|few minutes)", r"today itself", r"will be (blocked|closed|seized|frozen)",
        r"before midnight", r"hurry up", r"\bquickly\b", "तुरंत", "जल्दी कीजिए", "जल्दी करो", "अभी के अभी", "आज ही",
        "એક કલાકમાં", "જલ્દી કરો", "જલ્દી બોલો", "તરત", "બંધ થઈ જશે",
    ],
    SECRECY: [
        r"(don'?t|do not) tell (anyone|anybody|your family)", r"not even your family", r"keep the (video )?call on",
        r"(don'?t|do not) (cut|disconnect|hang up)", r"stay on the (call|line)",
        "किसी को कुछ मत", "किसी को मत", "मत बताइए", "कॉल चालू रखिए", "फ़ोन मत काट", "फोन मत काट",
        "કોઈને ના કહેશો", "કોઈને કહેતા નહીં", "ફોન ના કાપ", "ફોન કાપશો નહીં",
    ],
    OTP_REQUEST: [
        r"\botp\b", r"\bcvv\b", r"one[- ]time password", r"\bupi pin\b", r"\batm pin\b",
        "ओटीपी", "पिन बताइए", "ઓટીપી", "પિન નંબર",
    ],
    MONEY_REQUEST: [
        r"transfer (all |the )?(your )?(money|funds|amount)", r"verification account", r"safe account",
        r"pay (the )?(customs|duty|fee|fine|charges)", r"customs duty", r"send (the )?money",
        "ट्रांसफर कर", "ट्रांसफ़र कर", "पैसे भेज", "ड्यूटी", "पेमेंट कर दीजिए",
        "ટ્રાન્સફર કર", "પૈસા મોકલ", "પૈસા ભરો",
    ],
    REMOTE_ACCESS: [
        r"any ?desk", r"team ?viewer", r"quick ?support", r"screen ?shar", r"\bapk\b", r"download (the |this |an? )?app",
        r"(click|open) (on )?(the|this) link", "एनीडेस्क", "स्क्रीन शेयर", "ऐप डाउनलोड",
        "એનીડેસ્ક", "સ્ક્રીન શેર", "એપ ડાઉનલોડ",
    ],
}

_COMPILED = {code: [re.compile(p, re.IGNORECASE) for p in pats] for code, pats in _RULES.items()}


def match_rules(*texts: str) -> list[dict]:
    """Return one {code, evidence} per flag whose keywords appear in any of the given texts."""
    found = []
    for code, patterns in _COMPILED.items():
        for text in texts:
            if not text:
                continue
            hit = next((m for p in patterns if (m := p.search(text))), None)
            if hit:
                found.append({"code": code, "evidence": _snippet(text, hit.start(), hit.end())})
                break
    return found


def _snippet(text: str, start: int, end: int, pad: int = 28) -> str:
    a, b = max(0, start - pad), min(len(text), end + pad)
    return ("…" if a else "") + text[a:b].strip() + ("…" if b < len(text) else "")
