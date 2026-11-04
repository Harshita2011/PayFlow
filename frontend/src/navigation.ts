export type DashboardView = 'home' | 'send' | 'scan' | 'qr' | 'transactions' | 'account' | 'profile' | 'contacts' | 'request' | 'requests' | 'split-create' | 'splits' | 'self'

export const destinations: { id: DashboardView; label: string; icon: string; description: string }[] = [
  { id: 'home', label: 'Home', icon: 'home', description: 'Your money, at a glance. All simulated.' },
  { id: 'send', label: 'Send Money', icon: 'send', description: 'Verify a recipient, review the details, then confirm.' },
  { id: 'request', label: 'Request Money', icon: 'history', description: 'Ask for simulated money. The payer always chooses whether to confirm.' },
  { id: 'requests', label: 'Requests', icon: 'history', description: 'Review incoming and outgoing requests. No automatic payments.' },
  { id: 'contacts', label: 'Contacts', icon: 'user', description: 'Your private address book, favorites, and recent contacts.' },
  { id: 'split-create', label: 'Split Expenses', icon: 'user', description: 'Record an external expense and request exact fictional contributions.' },
  { id: 'splits', label: 'My Splits', icon: 'history', description: 'Created and shared expenses, contribution progress, and settlement history.' },
  { id: 'self', label: 'Transfer to Self', icon: 'bank', description: 'Move simulated funds between your own accounts. No change to your total funds.' },
  { id: 'scan', label: 'Scan QR', icon: 'scan', description: 'Scan a PayFlow code to find a verified recipient.' },
  { id: 'qr', label: 'My QR', icon: 'qr', description: 'Your public PayFlow identity, ready to share.' },
  { id: 'transactions', label: 'Transactions', icon: 'history', description: 'Follow every fictional rupee. View a payment for its receipt.' },
  { id: 'account', label: 'My Bank Accounts', icon: 'bank', description: 'Up to four demo accounts, one primary source, and a user-wide funding allowance.' },
  { id: 'profile', label: 'Profile', icon: 'user', description: 'Your account details and session information.' },
]
