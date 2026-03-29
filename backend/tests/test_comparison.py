"""单元测试：比对服务核心功能"""

import json
from app.services.comparison import levenshtein_similarity, normalize_json_content, truncate_content


class TestLevenshteinSimilarity:
    """测试 Levenshtein 相似度计算"""

    def test_identical_strings(self):
        """完全相同的字符串相似度应该为 1.0"""
        a = "hello world"
        b = "hello world"
        assert levenshtein_similarity(a, b) == 1.0

    def test_completely_different(self):
        """完全不同的字符串相似度接近 0.0"""
        a = "aaaaa"
        b = "bbbbb"
        sim = levenshtein_similarity(a, b)
        assert sim == 0.0

    def test_partially_similar(self):
        """部分相似的字符串相似度在 0-1 之间"""
        a = "hello world"
        b = "hello word"
        sim = levenshtein_similarity(a, b)
        assert 0.8 < sim < 1.0

    def test_empty_strings(self):
        """两个空字符串相似度为 1.0"""
        assert levenshtein_similarity("", "") == 1.0

    def test_one_empty_one_nonempty(self):
        """一个空一个非空相似度为 0"""
        assert levenshtein_similarity("", "hello") == 0.0


class TestNormalizeJsonContent:
    """测试 JSON 标准化"""

    def test_remove_markdown_wrapper(self):
        """测试去除 Markdown 包裹"""
        content = """```json
{
  "name": "test",
  "value": 123
}
```"""
        normalized = normalize_json_content(content)
        # 应该去除包裹，但是内容保留
        assert "```" not in normalized
        assert "name" in normalized
        assert "test" in normalized

    def test_different_order_same_content(self):
        """不同顺序相同内容标准化后应该相同"""
        a = '{"b": 2, "a": 1}'
        b = '{"a": 1, "b": 2}'
        norm_a = normalize_json_content(a)
        norm_b = normalize_json_content(b)
        # 排序 key 之后应该相同
        assert norm_a == norm_b

    def test_parse_failure_returns_original(self):
        """解析失败返回原文，不抛异常"""
        invalid_json = '{"b": 2, "a": 1'  # 缺少闭合括号
        result = normalize_json_content(invalid_json)
        assert result == invalid_json

    def test_non_json_returns_original(self):
        """不是 JSON 的返回原文"""
        text = "这是一段普通文本"
        assert normalize_json_content(text) == text

    def test_empty_string(self):
        """空字符串处理正确"""
        assert normalize_json_content("") == ""


class TestTruncateContent:
    """测试超长内容截断"""

    def test_short_content_not_truncated(self):
        """短内容不截断"""
        content = "short content"
        assert truncate_content(content) == content

    def test_long_content_truncated(self):
        """长内容截断并添加标记"""
        content = "x" * 10000
        result = truncate_content(content)
        assert len(result) < 10000
        assert "[...truncated]" in result


class TestJsonNormalizationIntegration:
    """JSON 标准化集成测试：多种格式转换为相同输出"""

    def test_different_formats_same_content(self):
        """不同格式相同内容标准化后得到相同字符串"""
        # 不同的空格和顺序
        format1 = '{"name": "test", "id": 123, "active": true}'
        format2 = '''{
            "id": 123,
            "name": "test",
            "active": true
        }'''
        format3 = '{"active":true,"id":123,"name":"test"}'

        norm1 = normalize_json_content(format1)
        norm2 = normalize_json_content(format2)
        norm3 = normalize_json_content(format3)

        assert norm1 == norm2 == norm3

    def test_with_markdown_wrapper(self):
        """带 Markdown 包裹的 JSON 标准化后和不带包裹相同"""
        wrapped = """```json
{"name": "test", "id": 123}
```"""
        unwrapped = '{"name": "test", "id": 123}'

        norm_wrapped = normalize_json_content(wrapped)
        norm_unwrapped = normalize_json_content(unwrapped)

        assert norm_wrapped == norm_unwrapped
