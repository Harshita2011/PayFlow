export type DashboardView = 'home' | 'send' | 'scan' | 'qr' | 'transactions' | 'account' | 'profile' | 'contacts' | 'request' | 'requests'

export const destinations: { id: DashboardView; label: string; icon: string; description: string }[] = [
  { id: 'home', label: 'Home', icon: 'home', description: 'Your money, at a glance. All simulated.' },
  { id: 'send', label: 'Send Money', icon: 'send', description: 'Verify a recipient, review the details, then confirm.' },
  { id: 'request', label: 'Request Money', icon: 'history', description: 'Ask for simulated money. The payer always chooses whether to confirm.' },
  { id: 'requests', label: 'Requests', icon: 'history', description: 'Review incoming and outgoing requests. No automatic payments.' },
  { id: 'contacts', label: 'Contacts', icon: 'user', description: 'Your private address book, favorites, and recent contacts.' },
  { id: 'scan', label: 'Scan QR', icon: 'scan', description: 'Scan a PayFlow code to find a verified recipient.' },
  { id: 'qr', label: 'My QR', icon: 'qr', description: 'Your public PayFlow identity, ready to share.' },
  { id: 'transactions', label: 'Transactions', icon: 'history', description: 'Follow every fictional rupee. View a payment for its receipt.' },
  { id: 'account', label: 'Bank Account', icon: 'bank', description: 'One demo account. Your own sandbox identity.' },
  { id: 'profile', label: 'Profile', icon: 'user', description: 'Your account details and session information.' },
]
