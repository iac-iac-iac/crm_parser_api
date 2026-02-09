"""Нормализация телефонных номеров"""
import phonenumbers
from phonenumbers import NumberParseException
from typing import Tuple, Optional

class PhoneNormalizer:
    @staticmethod
    def normalize(raw_phone: str) -> Tuple[Optional[str], bool]:
        if not raw_phone:
            return None, False

        digits = ''.join(filter(str.isdigit, raw_phone))
        
        # 8XXXXXXXXXX -> 7XXXXXXXXXX
        if digits.startswith('8') and len(digits) == 11:
            digits = '7' + digits[1:]
        
        if digits.startswith('7'):
            digits = '+' + digits

        try:
            parsed = phonenumbers.parse(digits, "RU")
            if phonenumbers.is_valid_number(parsed):
                normalized = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
                return normalized, True
        except NumberParseException:
            pass

        return None, False
