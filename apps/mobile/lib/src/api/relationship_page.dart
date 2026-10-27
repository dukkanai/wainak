/// One bounded relationship page. This does not accept arbitrary query strings.
String relationshipPagePath(String? cursor) {
  if (cursor == null) return '/v1/relationships';
  if (!RegExp(r'^rel_[0-9a-f]{32}$').hasMatch(cursor)) {
    throw ArgumentError('Invalid relationship cursor');
  }
  return '/v1/relationships?cursor=$cursor';
}

class RelationshipPage {
  RelationshipPage._(this.items, this.nextCursor);
  final List<Map<String, dynamic>> items;
  final String? nextCursor;
  static const size = 20;

  factory RelationshipPage.fromJson(
    Map<String, dynamic> data, {
    String? after,
  }) {
    relationshipPagePath(after);
    const bad = FormatException('Invalid relationship page');
    if (data.length != 2 ||
        !data.containsKey('items') ||
        !data.containsKey('next_cursor') ||
        data['items'] is! List) {
      throw bad;
    }
    final raw = data['items'] as List;
    if (raw.length > size) throw bad;
    final rows = <Map<String, dynamic>>[];
    var previous = after;
    for (final item in raw) {
      if (item is! Map<String, dynamic>) throw bad;
      final id = item['id'];
      if (id is! String ||
          !RegExp(r'^rel_[0-9a-f]{32}$').hasMatch(id) ||
          (previous != null && id.compareTo(previous) <= 0)) {
        throw bad;
      }
      rows.add(Map.unmodifiable(item));
      previous = id;
    }
    final next = data['next_cursor'];
    if (next != null &&
        (next is! String || raw.length != size || next != previous)) {
      throw bad;
    }
    return RelationshipPage._(List.unmodifiable(rows), next as String?);
  }
}
