import 'dart:convert';
import '../api/transport.dart';

enum IdentityStage { signedOut, pendingVerification, authenticated }

class IdentityFailure implements Exception {
  const IdentityFailure(this.code, this.message);
  final String code, message;
  @override
  String toString() => 'IdentityFailure($code)';
}

/// Native synthetic identity adapter. Tokens/passwords/codes are never persisted
/// or logged. Pending allauth401 is not confused with domain-session expiry.
class IdentityClient {
  IdentityClient({
    required this.baseUri,
    required this.transport,
    DateTime Function()? clock,
  }) : _clock = clock ?? DateTime.now {
    if (baseUri.scheme != 'http' ||
        !['127.0.0.1', 'localhost', '::1', '[::1]'].contains(baseUri.host) ||
        baseUri.userInfo.isNotEmpty ||
        baseUri.hasQuery ||
        baseUri.hasFragment ||
        !['', '/'].contains(baseUri.path)) {
      throw ArgumentError('Explicit loopback identity fixture origin required');
    }
  }
  final Uri baseUri;
  final ApiTransport transport;
  final DateTime Function() _clock;
  static const policyVersion = 'dev-2026-10-24';
  static const _auth = '/_allauth/app/v1/';
  String? _token, _accountLabel;
  int _epoch = 0;
  bool _closed = false;
  IdentityStage _stage = IdentityStage.signedOut;
  Map<String, dynamic>? _identity;
  IdentityStage get stage => _stage;
  int get sessionGeneration => _epoch;
  String? get accountLabel => _accountLabel;
  bool get authenticated => _stage == IdentityStage.authenticated;
  Map<String, dynamic>? get identity =>
      _identity == null ? null : Map.unmodifiable(_identity!);

  void _current(int epoch) {
    if (_closed || _epoch != epoch) {
      throw const IdentityFailure(
        'stale_response',
        'تغيرت الجلسة؛ تجاهلنا الاستجابة القديمة.',
      );
    }
  }

  void forgetLocalSession() {
    _epoch++;
    _token = null;
    _identity = null;
    _accountLabel = null;
    _stage = IdentityStage.signedOut;
  }

  String _email(String value) {
    final email = value.trim().toLowerCase();
    if (email.length > 100 ||
        !RegExp(
          r'^[a-z0-9][a-z0-9._-]{0,63}@example\.invalid$',
        ).hasMatch(email)) {
      throw const IdentityFailure(
        'fixture_email_required',
        'استخدم عنوان اختبار ينتهي بـ example.invalid فقط؛ لا بريد حقيقي.',
      );
    }
    return email;
  }

  void _password(String value, {bool creating = false}) {
    if (value.isEmpty ||
        value.length > 1024 ||
        (creating && value.length < 12)) {
      throw IdentityFailure(
        'password_required',
        creating
            ? 'يلزم سر اختبار من 12 محرفًا على الأقل؛ لا تعِد استخدام كلمة مرور حقيقية.'
            : 'أدخل كلمة مرور الاختبار.',
      );
    }
  }

  Future<_Reply> _send(
    String method,
    String path,
    int epoch, {
    Map<String, dynamic>? body,
    String? session,
  }) async {
    _current(epoch);
    final encoded = method == 'GET'
        ? null
        : jsonEncode(body ?? <String, dynamic>{});
    if (encoded != null && utf8.encode(encoded).length > 16384) {
      throw const IdentityFailure(
        'input_too_large',
        'حجم الطلب أكبر من المسموح.',
      );
    }
    ApiResponse response;
    try {
      response = await transport.send(method, baseUri.resolve(path), {
        'Accept': 'application/json',
        if (method != 'GET') 'Content-Type': 'application/json',
        if (session != null) 'X-Session-Token': session,
      }, encoded);
    } catch (_) {
      _current(epoch);
      throw const IdentityFailure(
        'network_uncertain',
        'تعذر تأكيد النتيجة. لا نعيد الطلب تلقائيًا؛ تحقق من الجلسة قبل التكرار.',
      );
    }
    _current(epoch);
    try {
      final value = jsonDecode(response.body);
      if (value is! Map<String, dynamic>) throw const FormatException();
      return _Reply(response.statusCode, value);
    } catch (_) {
      throw const IdentityFailure(
        'invalid_response',
        'استجابة غير متوافقة؛ لم نؤكد العملية.',
      );
    }
  }

  Never _reject(_Reply reply, int epoch, {bool expire = true}) {
    _current(epoch);
    final raw = reply.body['error'];
    final code = raw is Map ? raw['code'] : null;
    if (expire && (reply.status == 401 || reply.status == 410))
      forgetLocalSession();
    throw IdentityFailure(
      switch (code) {
        'consent_required' => 'consent_required',
        'reauthentication_required' => 'reauthentication_required',
        'reauthentication_failed' => 'reauthentication_failed',
        _ => switch (reply.status) {
          401 => 'session_expired',
          410 => 'flow_expired',
          429 => 'rate_limited',
          _ => 'request_rejected',
        },
      },
      switch (code) {
        'consent_required' =>
          'يلزم تحديث الموافقات من الخادم. هذه الواجهة لا تجددها تلقائيًا؛ تبقى إدارة الجلسة والحذف متاحة.',
        'reauthentication_required' =>
          'يلزم إثبات كلمة المرور حديثًا قبل هذا الإجراء.',
        _ => switch (reply.status) {
          401 => 'لم يثبت الدخول أو انتهت الجلسة؛ ابدأ تسجيل الدخول من جديد.',
          410 => 'انتهى مسار التحقق؛ أعد تسجيل الدخول للحصول على مسار حالي.',
          429 => 'طلبات كثيرة؛ انتظر قبل المحاولة. لا توجد إعادة تلقائية.',
          403 => 'لم يؤكد الخادم صلاحية هذا الإجراء أو كلمة المرور.',
          _ => 'لم تكتمل العملية. راجع مدخلات الاختبار دون تكرار تلقائي.',
        },
      },
    );
  }

  Future<void> _authState(_Reply reply, int epoch) async {
    _current(epoch);
    final meta = reply.body['meta'];
    final issued = meta is Map ? meta['session_token'] : null;
    if (issued != null &&
        (issued is! String || issued.isEmpty || issued.length > 4096)) {
      throw const IdentityFailure(
        'invalid_response',
        'استجابة جلسة غير متوافقة.',
      );
    }
    final token = issued as String? ?? _token;
    final data = reply.body['data'];
    final flows = data is Map ? data['flows'] : null;
    final pending =
        flows is List &&
        flows.any(
          (f) =>
              f is Map && f['id'] == 'verify_email' && f['is_pending'] == true,
        );
    if (reply.status == 401 &&
        meta is Map &&
        meta['is_authenticated'] == false &&
        token != null &&
        pending) {
      _token = token;
      _identity = null;
      _stage = IdentityStage.pendingVerification;
      _epoch++; // Invalidate older pending/auth requests even if they share a token.
      return;
    }
    if (reply.status == 200 &&
        meta is Map &&
        meta['is_authenticated'] == true &&
        token != null) {
      final proof = await _send(
        'GET',
        '/identity/v1/me',
        epoch,
        session: token,
      );
      _current(epoch);
      if (proof.status != 200) _reject(proof, epoch);
      final me = proof.body;
      if (me['email_verified'] != true ||
          me['email_is_identity_verification'] != false ||
          me['mode'] != 'synthetic_identity_sandbox' ||
          me['id'] is! String ||
          !RegExp(
            r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$',
          ).hasMatch(me['id'] as String) ||
          me['domain_id'] is! String ||
          !RegExp(r'^usr_[0-9a-f]{32}$').hasMatch(me['domain_id'] as String) ||
          me['email'] is! String) {
        forgetLocalSession();
        throw const IdentityFailure(
          'invalid_identity',
          'لم يثبت وصول الحساب؛ لا توثيق هوية قانونية هنا.',
        );
      }
      final provenEmail = _email(me['email'] as String);
      if (_accountLabel != null && provenEmail != _accountLabel) {
        forgetLocalSession();
        throw const IdentityFailure(
          'actor_changed',
          'استجابة الحساب لا تطابق جلسة الدخول المطلوبة.',
        );
      }
      _token = token;
      _identity = Map.unmodifiable({
        for (final key in ['id', 'domain_id', 'email']) key: me[key],
      });
      _accountLabel = provenEmail;
      _stage = IdentityStage.authenticated;
      _epoch++; // Old resend/refresh replies cannot downgrade this verified session.
      return;
    }
    _reject(reply, epoch);
  }

  Future<void> signup({
    required String email,
    required String password,
    required int age,
    required bool adult,
    required bool muslim,
    required bool terms,
    required bool privacy,
  }) async {
    email = _email(email);
    _password(password, creating: true);
    if (age < 18 || age > 120 || !(adult && muslim && terms && privacy)) {
      throw const IdentityFailure(
        'consent_required',
        'يلزم بلوغ 18 سنة وإكمال الإقرارات؛ هذا ليس توثيق عمر.',
      );
    }
    forgetLocalSession();
    _accountLabel = email;
    final epoch = _epoch;
    final now = _clock().toUtc();
    final year = now.year - age;
    final lastDay = DateTime.utc(year, now.month + 1, 0).day;
    final birth = DateTime.utc(
      year,
      now.month,
      now.day > lastDay ? lastDay : now.day,
    );
    final reply = await _send(
      'POST',
      '${_auth}auth/signup',
      epoch,
      body: {
        'email': email,
        'password': password,
        'birth_date':
            '${birth.year.toString().padLeft(4, '0')}-${birth.month.toString().padLeft(2, '0')}-${birth.day.toString().padLeft(2, '0')}',
        'is_muslim': true,
        'terms_version': policyVersion,
        'privacy_version': policyVersion,
      },
    );
    await _authState(reply, epoch);
  }

  Future<void> login(String email, String password) async {
    email = _email(email);
    _password(password);
    forgetLocalSession();
    _accountLabel = email;
    final epoch = _epoch;
    await _authState(
      await _send(
        'POST',
        '${_auth}auth/login',
        epoch,
        body: {'email': email, 'password': password},
      ),
      epoch,
    );
  }

  Future<void> verify(String code) async {
    if (stage != IdentityStage.pendingVerification ||
        code.trim().isEmpty ||
        code.length > 256) {
      throw const IdentityFailure(
        'pending_required',
        'يلزم مسار تحقق حالي ورمز البريد الاختباري، لا رابط إعادة كلمة المرور.',
      );
    }
    final epoch = _epoch;
    final reply = await _send(
      'POST',
      '${_auth}auth/email/verify',
      epoch,
      body: {'key': code.trim()},
      session: _token,
    );
    if (![200, 401].contains(reply.status)) _reject(reply, epoch);
    await _authState(reply, epoch);
  }

  Future<void> resend() async {
    if (stage != IdentityStage.pendingVerification)
      throw const IdentityFailure(
        'pending_required',
        'لا يوجد مسار تحقق حالي.',
      );
    final epoch = _epoch;
    final reply = await _send(
      'POST',
      '${_auth}auth/email/verify/resend',
      epoch,
      session: _token,
    );
    _current(epoch);
    if (reply.status != 200) _reject(reply, epoch);
    final meta = reply.body['meta'];
    if (meta is Map && meta.containsKey('session_token')) {
      final token = meta['session_token'];
      if (token is! String || token.isEmpty || token.length > 4096)
        throw const IdentityFailure(
          'invalid_response',
          'استجابة جلسة غير متوافقة.',
        );
      if (token != _token) {
        _token = token;
        _epoch++;
      }
    }
  }

  Future<void> refreshSession() async {
    if (_token == null)
      throw const IdentityFailure('session_required', 'سجّل الدخول أولًا.');
    final epoch = _epoch;
    await _authState(
      await _send('GET', '${_auth}auth/session', epoch, session: _token),
      epoch,
    );
  }

  Future<void> logout({bool everywhere = false}) async {
    final token = _token;
    forgetLocalSession();
    final epoch = _epoch;
    if (token == null) return;
    final reply = await _send(
      everywhere ? 'POST' : 'DELETE',
      everywhere ? '/identity/v1/logout-all' : '${_auth}auth/session',
      epoch,
      session: token,
    );
    _current(epoch);
    final ok = everywhere
        ? reply.status == 200 && reply.body['revoked_all'] == true
        : reply.status == 401 &&
              reply.body['status'] == 401 &&
              reply.body['meta'] is Map &&
              reply.body['meta']['is_authenticated'] == false;
    if (!ok)
      throw const IdentityFailure(
        'revocation_uncertain',
        'مُسحت الجلسة من التطبيق، لكن لم نؤكد إبطالها على الخادم.',
      );
  }

  Future<void> deleteAccount(
    String password, {
    required bool confirmed,
    int? expectedGeneration,
  }) async {
    if (expectedGeneration != null && expectedGeneration != _epoch) {
      throw const IdentityFailure(
        'actor_changed',
        'تغيرت الجلسة منذ فتح التأكيد؛ لم نرسل طلب حذف.',
      );
    }
    _password(password);
    if (!confirmed || _token == null || stage == IdentityStage.signedOut) {
      throw const IdentityFailure(
        'confirmation_required',
        'يلزم تأكيد الحذف من جلسة مملوكة حالية.',
      );
    }
    final epoch = _epoch;
    final pending = stage == IdentityStage.pendingVerification;
    if (!pending) {
      final proof = await _send(
        'POST',
        '/identity/v1/reauthenticate',
        epoch,
        body: {'password': password},
        session: _token,
      );
      if (proof.status != 200 || proof.body['reauthenticated'] != true)
        _reject(proof, epoch);
    }
    final reply = await _send(
      'DELETE',
      pending ? '/identity/v1/pending-account' : '/identity/v1/me',
      epoch,
      body: {'confirmation': 'DELETE', if (pending) 'password': password},
      session: _token,
    );
    if (reply.status != 200 || reply.body['identity_erased'] != true)
      _reject(reply, epoch);
    forgetLocalSession();
  }

  Future<Map<String, dynamic>> domain(
    String method,
    String path, {
    Map<String, dynamic>? body,
  }) async {
    const allowed = {
      'GET /v1/me',
      'PUT /v1/me/profile',
      'PUT /v1/me/preferences',
      'GET /v1/me/assessment',
      'POST /v1/me/assessment/answers',
      'GET /v1/candidates',
    };
    if (!allowed.contains('$method $path'))
      throw ArgumentError('Unsupported identity profile operation');
    if (!authenticated)
      throw const IdentityFailure(
        'authenticated_required',
        'أكمل إثبات البريد وتسجيل الدخول أولًا.',
      );
    final epoch = _epoch;
    final reply = await _send(method, path, epoch, body: body, session: _token);
    _current(epoch);
    if (reply.status < 200 || reply.status >= 300) _reject(reply, epoch);
    return reply.body;
  }

  void close() {
    forgetLocalSession();
    _closed = true;
    transport.close();
  }
}

class _Reply {
  const _Reply(this.status, this.body);
  final int status;
  final Map<String, dynamic> body;
}
