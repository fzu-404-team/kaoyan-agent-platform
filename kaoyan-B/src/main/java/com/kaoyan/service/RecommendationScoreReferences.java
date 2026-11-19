package com.kaoyan.service;

import com.kaoyan.common.ApiException;
import com.kaoyan.dto.response.ScoreStatisticVO;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.dao.DataAccessException;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

/** Adds historical total-score references after the Agent has screened admissions criteria. */
@Slf4j
@Service
@RequiredArgsConstructor
public class RecommendationScoreReferences {
    private static final Map<String, String> ENGLISH = Map.of("201", "1", "204", "2");
    private static final Map<String, String> MATH = Map.of("301", "1", "302", "2", "303", "3");
    private static final List<String> CANDIDATE_FIELDS = List.of("candidates", "unverifiedCandidates");

    private final SchoolScoreStatistics statistics;

    public record MockScore(int total, String examCombo) {}

    public record ScoreReference(String programId, int year, double retestLine, String examCombo, BigDecimal gap) {}

    private record Exam(String combo, String majorCode) {}

    /** Validate the optional public score independently of the Agent request. */
    public static MockScore parseMockScore(Object value) {
        if (!(value instanceof Map<?, ?> score) || !score.keySet().equals(Set.of("total", "examCombo"))
                || !(score.get("total") instanceof Integer total) || total < 0 || total > 500
                || !(score.get("examCombo") instanceof String combo) || !combo.matches("[12][123]408")) {
            throw new ApiException(400, "模考总分须为0至500的整数，并选择对应的初试科目组合");
        }
        return new MockScore(total, combo);
    }

    /** Attach read-only references, preserving the original shortlist if the score store is unavailable. */
    public void enrich(Map<String, Object> result, MockScore mock) {
        var lookups = new HashMap<Exam, List<SchoolScoreStatistics.ComparisonRow>>();
        var references = new LinkedHashMap<String, ScoreReference>();
        try {
            for (String field : CANDIDATE_FIELDS) {
                for (var candidate : candidates(result.get(field))) {
                    Exam exam = exam(candidate);
                    if (exam == null) continue;
                    var rows = lookups.computeIfAbsent(exam,
                            key -> statistics.forComparison(key.combo(), null, key.majorCode(), null));
                    if (rows == null) return; // V16 is optional.
                    ScoreReference reference = reference(candidate, exam, rows, mock);
                    if (reference != null) references.put(reference.programId(), reference);
                }
            }
        } catch (DataAccessException exception) {
            log.warn("recommendation score references unavailable: {}", exception.getClass().getSimpleName());
            return;
        }
        if (references.isEmpty()) return;
        result.put("scoreReferences", List.copyOf(references.values()));
        // score-match-v1 already selected and ordered the candidates by tier; keep that order.
        if (mock == null || result.containsKey("scoreFilter")) return;

        var preferences = result.get("preferences") instanceof Map<?, ?> map ? map : Map.of();
        var profile = result.get("profileSnapshot") instanceof Map<?, ?> map ? map : Map.of();
        List<?> regions = preferences.get("regions") instanceof List<?> list ? list : List.of();
        Object targetSchool = profile.get("targetSchool");
        var order = Comparator.<Map<?, ?>>comparingInt(c -> regions.contains(c.get("region")) ? 0 : 1)
                .thenComparingInt(c -> c.get("school").equals(targetSchool) ? 0 : 1);
        var verified = candidates(result.get("candidates")).stream().map(c -> c.get("school")).toList();
        for (String field : CANDIDATE_FIELDS) {
            var items = candidates(result.get(field));
            if (items.size() < 2) continue;
            var preference = "unverifiedCandidates".equals(field)
                    ? order.thenComparingInt(c -> verified.contains(c.get("school")) ? 1 : 0) : order;
            items.sort(preference.thenComparingInt(c -> scorePriority(references.get(c.get("programId")))));
            result.put(field, items);
        }
    }

    private static List<Map<?, ?>> candidates(Object value) {
        var candidates = new ArrayList<Map<?, ?>>();
        if (value instanceof List<?> list) {
            for (Object item : list) {
                if (item instanceof Map<?, ?> candidate && candidate.get("school") instanceof String) {
                    candidates.add(candidate);
                }
            }
        }
        return candidates;
    }

    private static Exam exam(Map<?, ?> candidate) {
        if (!(candidate.get("majorCode") instanceof String major) || !major.matches("[0-9]{6}")
                || !"full_time".equals(candidate.get("studyMode")) || "special".equals(candidate.get("admissionCategory"))
                || !(candidate.get("examSubjects") instanceof List<?> subjects) || subjects.size() != 4
                || !subjects.contains("101") || !subjects.contains("408")) return null;
        String english = subjectCode(subjects, ENGLISH);
        String math = subjectCode(subjects, MATH);
        return english == null || math == null ? null : new Exam(english + math + "408", major);
    }

    private static String subjectCode(List<?> subjects, Map<String, String> codes) {
        for (var entry : codes.entrySet()) {
            if (subjects.contains(entry.getKey())) return entry.getValue();
        }
        return null;
    }

    private static ScoreReference reference(Map<?, ?> candidate, Exam exam,
            List<SchoolScoreStatistics.ComparisonRow> rows, MockScore mock) {
        if (!(candidate.get("programId") instanceof String id) || !(candidate.get("year") instanceof Number year)
                || !(candidate.get("college") instanceof String college) || college.isBlank()) return null;
        var history = rows.stream()
                .filter(row -> candidate.get("school").equals(row.schoolName()))
                .map(SchoolScoreStatistics.ComparisonRow::score)
                .filter(score -> college.equals(score.college()) && score.year() < year.intValue())
                .toList();
        if (history.isEmpty()) return null;
        int latest = history.stream().mapToInt(ScoreStatisticVO::year).max().orElseThrow();
        var lines = history.stream().filter(score -> score.year() == latest).toList();
        Double line = lines.get(0).retestLine();
        if (line == null || line <= 0 || line > 500
                || lines.stream().anyMatch(score -> !score.flags().isEmpty() || !line.equals(score.retestLine()))) return null;
        BigDecimal gap = mock != null && mock.examCombo().equals(exam.combo())
                ? BigDecimal.valueOf(mock.total()).subtract(BigDecimal.valueOf(line)) : null;
        return new ScoreReference(id, latest, line, exam.combo(), gap);
    }

    private static int scorePriority(ScoreReference reference) {
        if (reference == null || reference.gap() == null) return 2;
        return reference.gap().signum() >= 0 ? 0 : 1;
    }
}
