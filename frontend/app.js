/* ─────────────────────────────────────────────────────────────
   MeTube Channel Watcher — Vue 3 SPA
   Uses Options API (works cleanly with Vue 3 CDN build)
───────────────────────────────────────────────────────────── */

const { createApp } = Vue;

// Axios instance targeting the same origin
const api = axios.create({ baseURL: '/api' });

createApp({

  // ── Data ──────────────────────────────────────────────────
  data() {
    return {
      view: 'channels',

      channels: [],
      history: [],
      settings: { metube_url: '', check_interval: 60, jellyfin_url: '', jellyfin_api_key: '' },

      loading: {
        channels: false,
        history: false,
        settings: false,
        savingSettings: false,
        channelVideos: false,
      },

      checkingAll: false,
      retryingAll: false,
      retryingAllChannel: false,
      jellyfinRefreshing: false,
      importing: false,

      // Channel videos view
      selectedChannel: null,
      channelVideos: [],

      // Hash routing
      _pendingRoute: false,

      // Mobile nav overlay
      navOpen: false,

      // Alert banner
      alert: null,
      _alertTimer: null,

      // MeTube health
      metubeStatus: { ok: null, checked_at: null },
      _statusPollTimer: null,

      // Add/Edit modal state
      modal: {
        instance: null,   // Bootstrap Modal instance
        isEdit: false,
        loading: false,
        editId: null,
      },
      form: {
        channel_id: '',
        name: '',
        start_date: '',
        download_dir: '',
        quality: 'best',
        format: 'any',
        enabled: true,
      },
    };
  },

  // ── Computed ──────────────────────────────────────────
  computed: {
    failedCount() {
      return this.history.filter(v => v.status === 'failed').length;
    },
    channelFailedCount() {
      return this.channelVideos.filter(v => v.status === 'failed').length;
    },
    sortedChannels() {
      return [...this.channels].sort((a, b) => a.name.localeCompare(b.name));
    },
    metubeStatusClass() {
      if (this.metubeStatus.ok === null) return 'unknown';
      return this.metubeStatus.ok ? 'ok' : 'error';
    },
    metubeStatusTooltip() {
      if (this.metubeStatus.ok === null) return 'MeTube: checking…';
      const when = this.metubeStatus.checked_at
        ? ` (${this.formatRelative(this.metubeStatus.checked_at)})`
        : '';
      return this.metubeStatus.ok
        ? `MeTube: reachable${when}`
        : `MeTube: unreachable${when}`;
    },
    availableQualityOptions() {
      const AUDIO_QUALITY = {
        mp3:  [{ value: 'best', label: 'Best available' }, { value: '320', label: '320 kbps' }, { value: '192', label: '192 kbps' }, { value: '128', label: '128 kbps' }],
        m4a:  [{ value: 'best', label: 'Best available' }, { value: '192', label: '192 kbps' }, { value: '128', label: '128 kbps' }],
        opus: [{ value: 'best', label: 'Best available' }],
        wav:  [{ value: 'best', label: 'Best available' }],
        flac: [{ value: 'best', label: 'Best available' }],
      };
      const VIDEO_QUALITY = [
        { value: 'best',  label: 'Best available' },
        { value: '2160',  label: '4K (2160p)' },
        { value: '1440',  label: '1440p' },
        { value: '1080',  label: '1080p' },
        { value: '720',   label: '720p' },
        { value: '480',   label: '480p' },
        { value: '360',   label: '360p' },
        { value: '240',   label: '240p' },
        { value: 'worst', label: 'Worst available' },
      ];
      return AUDIO_QUALITY[this.form.format] || VIDEO_QUALITY;
    },
  },

  // ── Watch ──────────────────────────────────────────────────
  watch: {
    'form.format'(newFmt) {
      // Reset quality to 'best' if the current value is not valid for the new format
      const opts = this.availableQualityOptions;
      if (!opts.find(o => o.value === this.form.quality)) {
        this.form.quality = 'best';
      }
    },
    navOpen(open) {
      document.body.style.overflow = open ? 'hidden' : '';
    },
  },

  // ── Lifecycle ─────────────────────────────────────────────
  mounted() {
    this.loadChannels();
    this.loadSettings();
    // Initialise Bootstrap modal
    this.modal.instance = new bootstrap.Modal(this.$refs.channelModalEl);
    // MeTube status dot tooltip — title is a live function so content is
    // always current when the tooltip is displayed
    this.$nextTick(() => {
      this._statusTooltip = new bootstrap.Tooltip(this.$refs.statusDot, {
        title: () => this.metubeStatusTooltip,
        placement: 'bottom',
      });
    });
    // Initial health fetch + poll every 60 s
    this.loadMetubeStatus();
    this._statusPollTimer = setInterval(() => this.loadMetubeStatus(), 60_000);
    // Hash-based routing: back/forward buttons
    window.addEventListener('hashchange', () => {
      if (this._pendingRoute) { this._pendingRoute = false; return; }
      this._applyRoute(this._parseHash());
    });
    // Apply the URL the page was opened with (bookmarks, direct links)
    this._applyRoute(this._parseHash());
  },

  // ── Methods ───────────────────────────────────────────────
  methods: {

    /* ── MeTube health ──────────────────────────────────── */
    async loadMetubeStatus() {
      try {
        const { data } = await api.get('/health/metube');
        this.metubeStatus = data;
      } catch {
        // Silently ignore — dot stays in its last-known state
      }
    },

    /* ── Navigation ─────────────────────────────────────── */

    // Parse window.location.hash into { view, channelId }
    _parseHash() {
      const hash = window.location.hash.replace(/^#\/?/, '');
      if (!hash) return { view: 'channels', channelId: null };
      const parts = hash.split('/');
      const view = parts[0] || 'channels';
      const channelId = parts[1] ? parseInt(parts[1], 10) : null;
      return { view, channelId };
    },

    // Set the URL hash without triggering the hashchange listener
    _setHash(view, channelId = null) {
      const hash = channelId ? `#${view}/${channelId}` : `#${view}`;
      if (window.location.hash === hash) return;
      this._pendingRoute = true;
      window.location.hash = hash;
    },

    // Apply a parsed route object to the app state
    async _applyRoute({ view, channelId }) {
      if (view === 'channels' && channelId) {
        let ch = this.channels.find(c => c.id === channelId);
        if (!ch) {
          try {
            const { data } = await api.get(`/channels/${channelId}`);
            ch = { ...data, _checking: false };
          } catch {
            this._setHash('channels');
            return;
          }
        }
        this.selectedChannel = ch;
        this.channelVideos = [];
        this.view = 'channel-videos';
        this.loadChannelVideos();
      } else if (view === 'history') {
        this.view = 'history';
        this.loadHistory();
      } else if (view === 'settings') {
        this.view = 'settings';
        this.loadSettings();
      } else {
        this.view = 'channels';
      }
    },

    switchView(v) {
      this.navOpen = false;
      this._setHash(v);
      this._applyRoute({ view: v, channelId: null });
    },

    /* ── Alert helper ───────────────────────────────────── */
    showAlert(message, type = 'success') {
      clearTimeout(this._alertTimer);
      this.alert = { message, type };
      this._alertTimer = setTimeout(() => { this.alert = null; }, 4000);
    },

    /* ── Date formatting ────────────────────────────────── */
    // Normalise an ISO string coming from the backend (which omits 'Z')
    // so JavaScript always treats it as UTC, not local time.
    _toUTC(iso) {
      return new Date(iso.endsWith('Z') ? iso : iso + 'Z');
    },

    formatDate(iso) {
      if (!iso) return '—';
      return this._toUTC(iso).toLocaleDateString(undefined, {
        year: 'numeric', month: 'short', day: 'numeric',
      });
    },

    formatRelative(iso) {
      if (!iso) return '—';
      const diff = Math.floor((Date.now() - this._toUTC(iso)) / 1000);
      if (diff < 0) {
        // Future time (e.g. next_retry_at)
        const abs = -diff;
        if (abs < 60)    return `in ${abs}s`;
        if (abs < 3600)  return `in ${Math.floor(abs / 60)}m`;
        if (abs < 86400) return `in ${Math.floor(abs / 3600)}h`;
        return `in ${Math.floor(abs / 86400)}d`;
      }
      if (diff < 60)   return `${diff}s ago`;
      if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
      if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
      return `${Math.floor(diff / 86400)}d ago`;
    },

    /* ── Channels API ───────────────────────────────────── */
    async loadChannels() {
      this.loading.channels = true;
      try {
        const { data } = await api.get('/channels');
        // Add transient reactive state for per-row spinner
        this.channels = data.map(ch => ({ ...ch, _checking: false }));
      } catch {
        this.showAlert('Failed to load channels', 'danger');
      } finally {
        this.loading.channels = false;
      }
    },

    openAddModal() {
      this.modal.isEdit = false;
      this.modal.editId = null;
      this.form = { channel_id: '', name: '', start_date: '', download_dir: '', quality: 'best', format: 'any', enabled: true };
      this.modal.instance.show();
    },

    openEditModal(ch) {
      this.modal.isEdit = true;
      this.modal.editId = ch.id;
      this.form = {
        channel_id: ch.channel_id,
        name: ch.name,
        start_date: ch.start_date ? ch.start_date.slice(0, 10) : '',
        download_dir: ch.download_dir || '',
        quality: ch.quality || 'best',
        format: ch.format || 'any',
        enabled: ch.enabled,
      };
      this.modal.instance.show();
    },

    async submitChannelForm() {
      this.modal.loading = true;
      try {
        const payload = {
          channel_id: this.form.channel_id,
          name: this.form.name || null,
          start_date: this.form.start_date
            ? new Date(this.form.start_date).toISOString()
            : null,
          download_dir: this.form.download_dir || null,
          quality: this.form.quality || 'best',
          format: this.form.format || 'any',
          enabled: this.form.enabled,
        };

        if (this.modal.isEdit) {
          const { data } = await api.put(`/channels/${this.modal.editId}`, payload);
          const idx = this.channels.findIndex(c => c.id === this.modal.editId);
          if (idx !== -1) this.channels[idx] = { ...data, _checking: false };
          this.showAlert(`Channel "${data.name}" updated`);
        } else {
          const { data } = await api.post('/channels', payload);
          this.channels.push({ ...data, _checking: false });
          this.showAlert(`Channel "${data.name}" added`);
        }

        this.modal.instance.hide();
      } catch (err) {
        const msg = err.response?.data?.detail || 'Failed to save channel';
        this.showAlert(msg, 'danger');
      } finally {
        this.modal.loading = false;
      }
    },

    async toggleEnabled(ch) {
      try {
        const { data } = await api.put(`/channels/${ch.id}`, { enabled: !ch.enabled });
        Object.assign(ch, { ...data, _checking: ch._checking });
      } catch {
        this.showAlert('Failed to update channel', 'danger');
      }
    },

    async deleteChannel(ch) {
      if (!confirm(`Delete channel "${ch.name}"?\n\nAll download history for this channel will also be removed.`)) return;
      try {
        await api.delete(`/channels/${ch.id}`);
        this.channels = this.channels.filter(c => c.id !== ch.id);
        this.showAlert(`Channel "${ch.name}" deleted`);
      } catch {
        this.showAlert('Failed to delete channel', 'danger');
      }
    },

    async checkChannel(ch) {
      ch._checking = true;
      try {
        await api.post(`/channels/${ch.id}/check`);
        this.showAlert(`Check triggered for "${ch.name}" — results will appear shortly`);
        // Refresh channel after a short delay so last_checked updates
        setTimeout(async () => {
          try {
            const { data } = await api.get(`/channels/${ch.id}`);
            Object.assign(ch, { ...data, _checking: false });
          } catch { ch._checking = false; }
        }, 3000);
      } catch {
        this.showAlert('Failed to trigger check', 'danger');
        ch._checking = false;
      }
    },

    /* ── Channel videos view ────────────────────────────── */
    openChannelVideos(ch) {
      this._setHash('channels', ch.id);
      this.selectedChannel = ch;
      this.channelVideos = [];
      this.view = 'channel-videos';
      this.loadChannelVideos();
    },

    async loadChannelVideos() {
      this.loading.channelVideos = true;
      try {
        const { data } = await api.get(`/channels/${this.selectedChannel.id}/videos`);
        this.channelVideos = data.map(v => ({ ...v, _retrying: false }));
        this.$nextTick(() => {
          document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(el => {
            bootstrap.Tooltip.getOrCreateInstance(el);
          });
        });
      } catch {
        this.showAlert('Failed to load channel videos', 'danger');
      } finally {
        this.loading.channelVideos = false;
      }
    },

    async retryAllFailedChannel() {
      this.retryingAllChannel = true;
      try {
        const { data } = await api.post(`/channels/${this.selectedChannel.id}/retry-failed`);
        const byId = Object.fromEntries(data.map(v => [v.id, v]));
        this.channelVideos = this.channelVideos.map(v =>
          byId[v.id] ? { ...byId[v.id], _retrying: false } : v
        );
        const succeeded = data.filter(v => v.status === 'sent').length;
        const stillFailed = data.filter(v => v.status === 'failed').length;
        if (data.length === 0) {
          this.showAlert('No failed downloads to retry');
        } else if (stillFailed === 0) {
          this.showAlert(`All ${succeeded} failed download(s) re-sent successfully`);
        } else {
          this.showAlert(`${succeeded} re-sent, ${stillFailed} still failing`, 'danger');
        }
        this.$nextTick(() => {
          document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(el => {
            bootstrap.Tooltip.getOrCreateInstance(el);
          });
        });
      } catch {
        this.showAlert('Failed to retry downloads', 'danger');
      } finally {
        this.retryingAllChannel = false;
      }
    },

    /* ── Global check ───────────────────────────────────── */
    async checkAll() {
      this.checkingAll = true;
      try {
        await api.post('/settings/check-all');
        this.showAlert('Full check triggered — new videos will be dispatched to MeTube');
        // Refresh channel list after a short delay
        setTimeout(() => this.loadChannels(), 5000);
      } catch {
        this.showAlert('Failed to trigger check', 'danger');
      } finally {
        setTimeout(() => { this.checkingAll = false; }, 3000);
      }
    },

    /* ── History API ────────────────────────────────────── */
    async loadHistory() {
      this.loading.history = true;
      try {
        const { data } = await api.get('/videos?limit=200');
        this.history = data.map(v => ({ ...v, _retrying: false }));
        // Initialise Bootstrap tooltips for error badges (after DOM update)
        this.$nextTick(() => {
          document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(el => {
            bootstrap.Tooltip.getOrCreateInstance(el);
          });
        });
      } catch {
        this.showAlert('Failed to load history', 'danger');
      } finally {
        this.loading.history = false;
      }
    },

    async retryVideo(v) {
      v._retrying = true;
      try {
        const { data } = await api.post(`/videos/${v.id}/retry`);
        Object.assign(v, { ...data, _retrying: false });
        this.showAlert(
          data.status === 'sent'
            ? `Re-sent "${data.title}" to MeTube`
            : `Retry failed for "${data.title}"`,
          data.status === 'sent' ? 'success' : 'danger'
        );
        // Re-initialise tooltips after DOM update
        this.$nextTick(() => {
          document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(el => {
            bootstrap.Tooltip.getOrCreateInstance(el);
          });
        });
      } catch {
        this.showAlert('Failed to retry download', 'danger');
        v._retrying = false;
      }
    },

    async retryAllFailed() {
      this.retryingAll = true;
      try {
        const { data } = await api.post('/videos/retry-failed');
        // Merge updated records back into history by id
        const byId = Object.fromEntries(data.map(v => [v.id, v]));
        this.history = this.history.map(v =>
          byId[v.id] ? { ...byId[v.id], _retrying: false } : v
        );
        const succeeded = data.filter(v => v.status === 'sent').length;
        const stillFailed = data.filter(v => v.status === 'failed').length;
        if (data.length === 0) {
          this.showAlert('No failed downloads to retry');
        } else if (stillFailed === 0) {
          this.showAlert(`All ${succeeded} failed download(s) re-sent successfully`);
        } else {
          this.showAlert(
            `${succeeded} re-sent, ${stillFailed} still failing`,
            'danger'
          );
        }
        this.$nextTick(() => {
          document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(el => {
            bootstrap.Tooltip.getOrCreateInstance(el);
          });
        });
      } catch {
        this.showAlert('Failed to retry downloads', 'danger');
      } finally {
        this.retryingAll = false;
      }
    },

    /* ── Settings API ───────────────────────────────────── */
    async loadSettings() {
      this.loading.settings = true;
      try {
        const { data } = await api.get('/settings');
        this.settings = { ...data };
      } catch {
        this.showAlert('Failed to load settings', 'danger');
      } finally {
        this.loading.settings = false;
      }
    },

    async saveSettings() {
      this.loading.savingSettings = true;
      try {
        const { data } = await api.put('/settings', {
          metube_url: this.settings.metube_url,
          check_interval: Number(this.settings.check_interval),
          jellyfin_url: this.settings.jellyfin_url,
          jellyfin_api_key: this.settings.jellyfin_api_key,
        });
        this.settings = { ...data };
        this.showAlert('Settings saved');
      } catch {
        this.showAlert('Failed to save settings', 'danger');
      } finally {
        this.loading.savingSettings = false;
      }
    },

    async refreshJellyfin() {
      this.jellyfinRefreshing = true;
      try {
        await api.post('/settings/jellyfin-refresh');
        this.showAlert('Jellyfin library refresh triggered');
      } catch (err) {
        const msg = err.response?.data?.detail || 'Jellyfin refresh failed';
        this.showAlert(msg, 'danger');
      } finally {
        this.jellyfinRefreshing = false;
      }
    },

    /* ── Export / Import ────────────────────────────────── */
    async exportChannels() {
      try {
        const { data } = await api.get('/channels/export');
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'channels-export.json';
        a.click();
        URL.revokeObjectURL(url);
      } catch {
        this.showAlert('Failed to export channels', 'danger');
      }
    },

    importChannels(event) {
      const file = event.target.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = async (e) => {
        this.importing = true;
        try {
          const parsed = JSON.parse(e.target.result);
          // Accept either a plain array or the full export object { channels: [...] }
          const payload = Array.isArray(parsed) ? { channels: parsed } : parsed;
          const { data: result } = await api.post('/channels/import', payload);
          const { added, skipped, errors } = result;
          if (errors.length > 0) {
            this.showAlert(
              `Import done: ${added} added, ${skipped} skipped, ${errors.length} error(s)`,
              'warning'
            );
          } else {
            this.showAlert(`Import done: ${added} added, ${skipped} already existed`);
          }
          if (added > 0) await this.loadChannels();
        } catch (err) {
          const msg = err.response?.data?.detail || 'Failed to import channels';
          this.showAlert(msg, 'danger');
        } finally {
          this.importing = false;
          // Reset so the same file can be re-selected next time
          event.target.value = '';
        }
      };
      reader.readAsText(file);
    },
  },
}).mount('#app');
