import pytest
import sys, os, math, json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

# Pure logic extracted from hipocampo_dedup.py for unit testing
def cosine_sim(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na * nb > 0 else 0


class TestCosineSimilarity:
    def test_identical_vectors(self):
        v = [1.0, 2.0, 3.0]
        assert cosine_sim(v, v) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        assert cosine_sim([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)

    def test_opposite_vectors(self):
        assert cosine_sim([1.0, 0.0], [-1.0, 0.0]) == pytest.approx(-1.0)

    def test_partial_similarity(self):
        sim = cosine_sim([1.0, 2.0, 3.0], [1.0, 2.0, 0.0])
        assert 0.5 < sim < 0.99

    def test_zero_vector(self):
        assert cosine_sim([0.0, 0.0], [1.0, 0.0]) == 0.0

    def test_both_zero(self):
        assert cosine_sim([0.0, 0.0], [0.0, 0.0]) == 0.0

    def test_high_dimensional(self):
        a = [0.1 * i for i in range(100)]
        b = [0.1 * i + 0.01 for i in range(100)]
        sim = cosine_sim(a, b)
        assert sim == pytest.approx(1.0, rel=1e-2)

    def test_1024_dim(self):
        a = [float(i % 10) for i in range(1024)]
        b = [float((i + 1) % 10) for i in range(1024)]
        sim = cosine_sim(a, b)
        assert 0.0 < sim < 1.0


# Test merge logic with synthetic data
class TestMergeExactGroups:
    def test_merge_groups_keep_first(self):
        groups = [
            ("texto duplicado", 3, [1, 2, 3]),
        ]
        keep_id = groups[0][2][0]
        remove_ids = groups[0][2][1:]
        assert keep_id == 1
        assert remove_ids == [2, 3]

    def test_multiple_groups(self):
        groups = [
            ("a", 2, [1, 5]),
            ("b", 3, [2, 3, 4]),
        ]
        all_remove = []
        for text, count, ids in groups:
            all_remove.extend(ids[1:])
        assert sorted(all_remove) == [3, 4, 5]


class TestFindSemanticGroups:
    def test_group_by_threshold(self):
        data = [
            {"id": 1, "text": "a", "embedding": [1.0, 0.0]},
            {"id": 2, "text": "b", "embedding": [0.99, 0.01]},
            {"id": 3, "text": "c", "embedding": [0.0, 1.0]},
        ]
        threshold = 0.9
        checked = set()
        groups = []
        for i in range(len(data)):
            if data[i]["id"] in checked:
                continue
            group = [data[i]]
            for j in range(i + 1, len(data)):
                if data[j]["id"] in checked:
                    continue
                sim = cosine_sim(data[i]["embedding"], data[j]["embedding"])
                if sim >= threshold:
                    group.append(data[j])
                    checked.add(data[j]["id"])
            if len(group) > 1:
                checked.add(data[i]["id"])
                groups.append(group)
        assert len(groups) == 1
        assert len(groups[0]) == 2
        assert groups[0][0]["id"] == 1
        assert groups[0][1]["id"] == 2

    def test_no_duplicates_below_threshold(self):
        data = [
            {"id": 1, "text": "a", "embedding": [1.0, 0.0]},
            {"id": 2, "text": "b", "embedding": [0.0, 1.0]},
        ]
        threshold = 0.9
        checked = set()
        groups = []
        for i in range(len(data)):
            if data[i]["id"] in checked:
                continue
            group = [data[i]]
            for j in range(i + 1, len(data)):
                if data[j]["id"] in checked:
                    continue
                sim = cosine_sim(data[i]["embedding"], data[j]["embedding"])
                if sim >= threshold:
                    group.append(data[j])
                    checked.add(data[j]["id"])
            if len(group) > 1:
                checked.add(data[i]["id"])
                groups.append(group)
        assert len(groups) == 0


class TestMergeSemanticLogic:
    def test_keep_longest_text(self):
        group = [
            {"id": 1, "text": "corto"},
            {"id": 2, "text": "texto mas largo para conservar"},
        ]
        best = max(group, key=lambda x: len(x["text"]))
        others = [x for x in group if x["id"] != best["id"]]
        assert best["id"] == 2
        assert len(others) == 1
        assert others[0]["id"] == 1
