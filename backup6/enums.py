import enum


class PanelType(str, enum.Enum):
    PASARGUARD = "pasarguard"
    SANAEI = "sanaei"         # 3x-ui (Sanaei)
    OVIRA = "ovira"           # OpenVPN / WireGuard


class ConnStatus(str, enum.Enum):
    UNKNOWN = "unknown"
    ONLINE = "online"
    OFFLINE = "offline"


class TxType(str, enum.Enum):
    CHARGE = "charge"
    PURCHASE = "purchase"
    REFUND = "refund"
    ADMIN_ADD = "admin_add"
    ADMIN_SUB = "admin_sub"
    REFERRAL = "referral"


class InvoiceKind(str, enum.Enum):
    WALLET_CHARGE = "wallet_charge"
    PURCHASE = "purchase"


class InvoiceStatus(str, enum.Enum):
    PENDING = "pending"                    # waiting for receipt
    AWAITING_REVIEW = "awaiting_review"    # receipt sent, admin must review
    PAID = "paid"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELED = "canceled"


ACTIVE_INVOICE_STATUSES = (InvoiceStatus.PENDING, InvoiceStatus.AWAITING_REVIEW)


class ReceiptStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class OrderStatus(str, enum.Enum):
    AWAITING_PAYMENT = "awaiting_payment"
    AWAITING_RECEIPT_REVIEW = "awaiting_receipt_review"
    PAID = "paid"
    PROVISIONING = "provisioning"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"
    REFUNDED = "refunded"


class ServiceStatus(str, enum.Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    DISABLED = "disabled"
    DEPLETED = "depleted"   # traffic finished
    DELETED = "deleted"


class TicketStatus(str, enum.Enum):
    OPEN = "open"
    ANSWERED = "answered"
    CLOSED = "closed"


class TicketTopic(str, enum.Enum):
    CONNECTION = "connection"
    SPEED = "speed"
    CONFIG = "config"
    PAYMENT = "payment"
    SUBSCRIPTION = "subscription"
    OTHER = "other"


class DiscountType(str, enum.Enum):
    PERCENT = "percent"
    FIXED = "fixed"
