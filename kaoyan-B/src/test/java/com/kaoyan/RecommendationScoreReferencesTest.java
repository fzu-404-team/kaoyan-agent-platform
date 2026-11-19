package com.kaoyan;

import com.kaoyan.common.ApiException;
import com.kaoyan.dto.response.ScoreStatisticVO;
import com.kaoyan.service.RecommendationScoreReferences;
import com.kaoyan.service.RecommendationScoreReferences.ScoreReference;
import com.kaoyan.service.SchoolScoreStatistics;
import com.kaoyan.service.SchoolScoreStatistics.ComparisonRow;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class RecommendationScoreReferencesTest {
    private final SchoolScoreStatistics statistics = mock(SchoolScoreStatistics.class);
    private final RecommendationScoreReferences references = new RecommendationScoreReferences(statistics);

    @Test
    void keepsIntentFirstAndUsesOnlyUnambiguousEarlierLinesWithTheSameExam() {
        var result = new LinkedHashMap<String, Object>();
        result.put("candidates", List.of(
                program("uncertain", "样例甲", "北京", "全日制学院"),
                program("above", "样例乙", "北京", "全日制学院"),
                program("intent", "样例丙", "北京", "全日制学院"),
                program("out-of-region", "样例丁", "江苏", "全日制学院")));
        result.put("preferences", Map.of("regions", List.of("北京")));
        result.put("profileSnapshot", Map.of("targetSchool", "样例丙"));
        when(statistics.forComparison("11408", null, "081200", null)).thenReturn(List.of(
                row("样例甲", "全日制学院", 2026, 300.0, List.of()),
                row("样例甲", "全日制学院", 2026, 310.0, List.of()),
                row("样例甲", "全日制学院", 2025, 280.0, List.of()),
                row("样例乙", "其他学院", 2026, 410.0, List.of()),
                row("样例乙", "全日制学院", 2027, 420.0, List.of()),
                row("样例乙", "全日制学院", 2026, 320.5, List.of()),
                row("样例丙", "全日制学院", 2026, 385.0, List.of()),
                row("样例丁", "全日制学院", 2026, 350.0, List.of("POSSIBLE_SAME_POOL"))));

        references.enrich(result, RecommendationScoreReferences.parseMockScore(Map.of("total", 350, "examCombo", "11408")));

        assertEquals(List.of(
                new ScoreReference("above", 2026, 320.5, "11408", new BigDecimal("29.5")),
                new ScoreReference("intent", 2026, 385.0, "11408", new BigDecimal("-35.0"))),
                result.get("scoreReferences"));
        assertEquals(List.of("intent", "above", "uncertain", "out-of-region"),
                ((List<?>) result.get("candidates")).stream().map(row -> ((Map<?, ?>) row).get("programId")).toList());
        verify(statistics, times(1)).forComparison("11408", null, "081200", null);
    }

    @Test
    void unmatchedMockComboLeavesTheReferenceWithoutADifferenceAndMissingTableLeavesTheShortlist() {
        var result = new LinkedHashMap<String, Object>();
        var catalog = List.of(program("ref", "样例甲", "北京", "全日制学院"));
        result.put("unverifiedCandidates", catalog);
        when(statistics.forComparison("11408", null, "081200", null)).thenReturn(null)
                .thenReturn(List.of(row("样例甲", "全日制学院", 2026, 320.0, List.of())));
        var mock = new RecommendationScoreReferences.MockScore(355, "22408");
        references.enrich(result, mock);
        assertFalse(result.containsKey("scoreReferences"));
        assertSame(catalog, result.get("unverifiedCandidates"));
        references.enrich(result, mock);
        assertEquals(List.of(new ScoreReference("ref", 2026, 320.0, "11408", null)), result.get("scoreReferences"));
    }

    /** score-match-v1 (2026-11-19): Python's tier order stands; references are still attached. */
    @Test
    void scoreFilteredResultsKeepTheirTierOrder() {
        var result = new LinkedHashMap<String, Object>();
        result.put("candidates", List.of(
                program("reach", "样例甲", "江苏", "全日制学院"),
                program("safe", "样例乙", "北京", "全日制学院")));
        result.put("preferences", Map.of("regions", List.of("北京")));
        result.put("scoreFilter", Map.of("ruleVersion", "score-match-v1"));
        when(statistics.forComparison("11408", null, "081200", null)).thenReturn(List.of(
                row("样例乙", "全日制学院", 2026, 300.0, List.of())));

        references.enrich(result, RecommendationScoreReferences.parseMockScore(Map.of("total", 350, "examCombo", "11408")));

        assertEquals(List.of("reach", "safe"),
                ((List<?>) result.get("candidates")).stream().map(row -> ((Map<?, ?>) row).get("programId")).toList());
        assertEquals(List.of(new ScoreReference("safe", 2026, 300.0, "11408", new BigDecimal("50.0"))),
                result.get("scoreReferences"));
    }

    @Test
    void mockScoreRequiresABoundedTotalAndAnExactExamCombination() {
        assertThrows(ApiException.class, () -> RecommendationScoreReferences.parseMockScore(Map.of("total", 501, "examCombo", "11408")));
        assertThrows(ApiException.class, () -> RecommendationScoreReferences.parseMockScore(Map.of("total", 330, "examCombo", "408")));
        assertThrows(ApiException.class, () -> RecommendationScoreReferences.parseMockScore(Map.of("total", "330", "examCombo", "11408")));
    }

    private static Map<String, Object> program(String id, String school, String region, String college) {
        return Map.of("programId", id, "school", school, "region", region, "college", college, "year", 2027,
                "majorCode", "081200", "studyMode", "full_time", "examSubjects", List.of("101", "201", "301", "408"));
    }

    private static ComparisonRow row(String school, String college, int year, Double line, List<String> flags) {
        return new ComparisonRow(1L, school, "北京", new ScoreStatisticVO(1L, year, college, "081200",
                "计算机科学与技术", "11408", line, null, null, null, null, 20, flags));
    }
}
