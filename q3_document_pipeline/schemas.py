"""Document types, fields to extract, and per-field reading hints."""

# key -> (display name, handwritten?, {field_key: (label, hint)})
DOC_TYPES: dict[str, dict] = {
    "aadhaar_card": {
        "name": "Aadhaar Card", "handwritten": False,
        "fields": {
            "aadhaar_number": ("Aadhaar Number", "12 digits, printed in 3 groups of 4. Return as 'XXXX XXXX XXXX'."),
            "full_name": ("Full Name", "As printed, including any title like Mr."),
            "date_of_birth": ("Date of Birth", "DD/MM/YYYY"),
            "address": ("Address", "Full address block on the back side, lines joined with ', '."),
        },
    },
    "pan_card": {
        "name": "PAN Card", "handwritten": False,
        "fields": {
            "pan_number": ("PAN Number", "10 chars: 5 letters, 4 digits, 1 letter."),
            "full_name": ("Full Name", "As printed."),
            "fathers_name": ("Father's Name", "As printed under Father's Name (keep prefixes like S/O if printed)."),
            "date_of_birth": ("Date of Birth", "DD/MM/YYYY"),
        },
    },
    "driving_licence": {
        "name": "Driving Licence", "handwritten": False,
        "fields": {
            "dl_number": ("DL Number", "As printed, keep spacing e.g. 'MH12 2021 0001234'."),
            "name": ("Name", "As printed."),
            "date_of_issue": ("Date of Issue", "DD/MM/YYYY (DOI / Date of Issue)."),
            "valid_till": ("Valid Till", "DD/MM/YYYY"),
        },
    },
    "passport": {
        "name": "Passport", "handwritten": False,
        "fields": {
            "passport_number": ("Passport Number", "1 letter + 7 digits."),
            "date_of_birth": ("Date of Birth", "DD/MM/YYYY"),
            "date_of_expiry": ("Date of Expiry", "DD/MM/YYYY"),
            "mrz_line_2": ("MRZ Line 2", "The 2nd (bottom) line of the machine-readable zone, copied EXACTLY as printed, "
                                         "character by character, including every '<' filler (count them carefully); no spaces."),
        },
    },
    "nach_mandate": {
        "name": "NACH / ECS Mandate", "handwritten": True,
        "fields": {
            "bank_account_number": ("Bank Account Number", "Handwritten digits in the 'Bank a/c number' boxes, one digit per box. Digits only."),
            "ifsc_code": ("IFSC Code", "Handwritten in boxes after 'IFSC'. Format: 4 letters + '0' + 6 alphanumerics (11 chars). The 5th char is always zero."),
            "bank_name": ("Bank Name", "Handwritten after 'with bank'."),
            "amount_figures": ("Amount (figures)", "The amount in figures after the ₹ symbol, digits only (no commas)."),
            "frequency": ("Frequency", "The ticked option among Monthly / Qtly / H.Yrly / Yrly / As & when presented. Return the option text."),
        },
    },
    "fatca_annexure": {
        "name": "FATCA Annexure Form", "handwritten": True,
        "fields": {
            "policy_number": ("Policy Number", "Handwritten in the 'Policy No' box. Digits only."),
            "tin_pan": ("TIN / PAN", "Handwritten in the 'Tax Identification Number (TIN)' column. Indian PAN format: 5 letters, 4 digits, 1 letter."),
            "fathers_name": ("Father's Name", "Handwritten after 'Father's Name' in Section 3."),
            "place_of_birth": ("Place of Birth", "Handwritten after 'Place of birth'."),
            "nationality": ("Nationality", "Handwritten after 'Nationality'."),
        },
    },
    "benefit_illustration_declaration": {
        "name": "Benefit Illustration Declaration", "handwritten": True,
        "fields": {
            "application_number": ("Application Number", "Digits only."),
            "policyholder_name": ("Policyholder Name", "Handwritten name of the policyholder/proposer."),
            "date": ("Date", "DD/MM/YYYY"),
            "place": ("Place", "Handwritten place."),
        },
    },
    "moral_hazard_questionnaire": {
        "name": "Moral Hazard Questionnaire", "handwritten": True,
        "fields": {
            "application_number": ("Application Number", "Digits only."),
            "name_of_life_assured": ("Name of Life Assured", "Handwritten."),
            "nominee_relationship": ("Nominee Relationship", "Relationship of the nominee to the life assured (e.g. Wife, Son)."),
            "date": ("Date", "DD/MM/YYYY"),
            "place": ("Place", "Handwritten place."),
        },
    },
    "multiple_policies_consent": {
        "name": "Multiple Policies Consent Form", "handwritten": True,
        "fields": {
            "proposer_name": ("Proposer Name", "Handwritten after 'Proposer / Life Assured Name'."),
            "reason_for_multiple_policies": ("Reason for Multiple Policies", "The text of the option whose checkbox is ticked (only the ticked one)."),
            "date": ("Date", "DD/MM/YYYY"),
            "place": ("Place", "Handwritten place."),
        },
    },
    "suitability_profiler_declaration": {
        "name": "Suitability Profiler Declaration", "handwritten": True,
        "fields": {
            "application_number": ("Application Number", "Digits only."),
            "name_of_life_assured": ("Name of Life Assured", "Handwritten."),
            "name_of_agent_sp": ("Name of Agent/SP", "Name of the agent / specified person (SP), handwritten or printed."),
            "date": ("Date", "DD/MM/YYYY"),
            "place": ("Place", "Handwritten place."),
        },
    },
}

OTHER = "other"
ALL_TYPES = list(DOC_TYPES) + [OTHER]

CLASSIFY_GUIDE = """- aadhaar_card: UIDAI Aadhaar card (12-digit number, 'Government of India', 'Aadhaar').
- pan_card: Income Tax Department 'Permanent Account Number Card'.
- driving_licence: Driving licence card (DL No., Valid Till, classes of vehicles).
- passport: Passport data page with MRZ lines (P<IND...).
- nach_mandate: 'NACH MANDATE INSTRUCTION' / ECS auto-debit form with bank a/c, IFSC, amount.
- fatca_annexure: 'ANNEXURE FORM' under Section 285BA Income Tax Act (FATCA/CRS tax residency declaration).
- benefit_illustration_declaration: declaration that the customer has understood the Benefit Illustration.
- moral_hazard_questionnaire: Moral hazard questionnaire / declaration (nominee relationship, income, reason for insurance).
- multiple_policies_consent: 'Split & Multiple Policies - Customer Consent form'.
- suitability_profiler_declaration: Suitability / Need analysis profiler declaration signed by customer and agent/SP.
- other: anything else (e.g. assignment request form, proposal form customer declaration)."""
