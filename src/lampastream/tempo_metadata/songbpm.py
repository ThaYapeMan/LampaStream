"""Reserved adapter: no request code, network client or saved-page assumptions.

The owner must supply permission/terms and a recorded page before implementation.
A follow-up replaces this adapter and changes its registry status to active;
stored rows remain frozen while the definition is obsolete.
"""


class Adapter:
    def lookup(self, identity):
        raise RuntimeError('SongBPM awaits owner permission and a saved-page fixture')
