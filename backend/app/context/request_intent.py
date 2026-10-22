"""Conservative request guards; observations never establish confirmation."""
import re

TENTATIVE = re.compile(r'\b(?:might need|may need|tentatively|will confirm later|mungkin nak|belum pasti)\b|可能要|暂定|还未确定|还没确定', re.I)
HISTORICAL = re.compile(r'\b(?:yesterday|semalam|last week|received already|dah sampai|arrived today|delivered today)\b|昨天|上次|已经收到|送来的|送到的|已收货', re.I)
CANCELLATION = re.compile(r'\b(?:cancel|cancelled|batal|batalkan|jangan hantar|jangan buat)\b|取消|不要送|不要制作', re.I)
INQUIRY = re.compile(r'\b(?:how much|what is the price|berapa harga|do you (?:do delivery|deliver)|available tak)\b|请问.*多少|如何收费|起订量', re.I)
REQUEST = re.compile(r'\b(?:need|want|send|prepare|deliver|nak|mahu|pesan|hantar)\b|要|请送|预订|下单', re.I)
FUTURE = re.compile(r'\b(?:tomorrow|tmr|tmrw|esok|lusa|next week)\b|明天|后天|下周', re.I)


def request_intent(text):
    if CANCELLATION.search(text):
        return 'CANCELLED'
    if TENTATIVE.search(text):
        return 'TENTATIVE'
    if HISTORICAL.search(text) and not (REQUEST.search(text) and FUTURE.search(text)):
        return 'NON_ORDER'
    if INQUIRY.search(text) and not REQUEST.search(text):
        return 'NON_ORDER'
    return 'UNCLASSIFIED'  # Never CONFIRMED; absence of a guard is not proof of intent.
