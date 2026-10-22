"""Conservative request guards; observations never establish confirmation."""
import re

ADVERSARIAL = re.compile(
    r'\b(?:ignore|disregard|cancel|override)\b.{0,30}\b(?:instructions|constraints|rules)\b|'
    r'\b(?:system override|admin note|assistant:)\b|'
    r'\b(?:skip|bypass)\b.{0,25}\b(?:review|human)\b|'
    r'\b(?:zero[ -]?cost|0 cost|pre-approved|free order)\b|'
    r'\b(?:system prompt|api key|environment variables)\b|'
    r'忽略系统规则|跳过人工审核|已全额付款|arahan sistem|tanpa semakan staf',
    re.I
)
TENTATIVE = re.compile(r'\b(?:might need|may need|tentatively|will confirm later|mungkin nak|belum pasti)\b|可能要|暂定|还未确定|还没确定', re.I)
HISTORICAL = re.compile(r'\b(?:yesterday|semalam|last week|received already|dah sampai|arrived today|delivered today)\b|昨天|上次|已经收到|送来的|送到的|已收货', re.I)
CANCELLATION = re.compile(r'\b(?:cancel|cancelled|batal|batalkan|jangan hantar|jangan buat)\b|取消|不要送|不要制作', re.I)
INQUIRY = re.compile(r'\b(?:how much|what is the price|berapa harga|do you (?:do delivery|deliver)|available tak)\b|请问.*多少|如何收费|起订量', re.I)
REQUEST = re.compile(r'\b(?:need|want|send|prepare|deliver|nak|mahu|pesan|hantar)\b|要|请送|预订|下单', re.I)
FUTURE = re.compile(r'\b(?:tomorrow|tmr|tmrw|esok|lusa|next week)\b|明天|后天|下周', re.I)
ORDER_IMPERATIVE = re.compile(r'\b(?:please\s+send|please\s+deliver|tolong\s+hantar|silakan\s+hantar|nak\s+order|我要订|请帮我送|确认下单)\b', re.I)


def request_intent(text):
    if ADVERSARIAL.search(text):
        return 'ADVERSARIAL'
    if CANCELLATION.search(text):
        return 'CANCELLED'
    if TENTATIVE.search(text):
        return 'TENTATIVE'
    if HISTORICAL.search(text) and not (REQUEST.search(text) and FUTURE.search(text)):
        return 'NON_ORDER'
    if INQUIRY.search(text) and not ORDER_IMPERATIVE.search(text):
        return 'NON_ORDER'
    return 'UNCLASSIFIED'  # Never CONFIRMED; absence of a guard is not proof of intent.
