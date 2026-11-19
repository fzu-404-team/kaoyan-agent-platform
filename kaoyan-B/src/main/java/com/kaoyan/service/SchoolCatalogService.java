package com.kaoyan.service;

import com.kaoyan.dto.response.ScoreStatisticVO;
import com.kaoyan.entity.School;
import com.kaoyan.entity.SchoolDetail;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.regex.Pattern;

/** Deterministic public catalog queries; no model, scraping, or business writes. */
@Service
@RequiredArgsConstructor
public class SchoolCatalogService {
    private final SchoolService schools;
    public static final String RELEASE = "school-catalog-v1";
    static final int SCORE_LIMIT = 30;

    /** Mirrors Python SCORE_TRIGGER / SCORE_EXCLUSION in agents/planning.py. */
    public static final Pattern SCORE = Pattern.compile(
        "复试线|分数线|录取分数|录取分|最低分|中位分|平均分|最高分|多少分|录取人数");
    private static final Pattern SCORE_EXCLUSION = Pattern.compile(
        "不要|不必|不需要|别查|别帮|示例|例如|这句话|这个指令|如何|怎么|功能介绍|假设|官网|网址|链接|核对|核验");

    /** One named school plus a score word; compound turns keep their original pipeline. */
    public static boolean scoreRequested(String query) {
        return SCORE.matcher(query).find() && !SCORE_EXCLUSION.matcher(query).find()
            && !AdmissionLinksValidator.compound(query) && !scoreSchoolNames(query).isEmpty();
    }

    /** Universities first; a "××学院" in the same turn is read as a department. */
    public static Set<String> scoreSchoolNames(String query) {
        Set<String> names = AdmissionLinksValidator.explicitSchoolNames(query);
        Set<String> universities = new LinkedHashSet<>();
        for (String name : names) if (name.endsWith("大学")) universities.add(name);
        return universities.isEmpty() ? names : universities;
    }

    /** Build a local plan before any provider or Python call. */
    public static Map<String, Object> plan(String query) {
        boolean admission = AdmissionLinksValidator.requested(query);
        boolean score = !admission && scoreRequested(query);
        if (!admission && !score) return null;
        if (admission && query.matches("(?s).*(官网|网址|链接|核对|核验).*")) return null;
        Set<String> names = score ? scoreSchoolNames(query) : AdmissionLinksValidator.explicitSchoolNames(query);
        Set<String> years = matches(query, "(?<!\\d)(20\\d{2}|2100)(?:年)?(?!\\d)", 1);
        Set<String> majors = matches(query, "(?<!\\d)\\d{6}(?!\\d)", 0);
        Map<String, Object> plan = new LinkedHashMap<>();
        plan.put("action", "SCHOOL_LOOKUP");
        plan.put("standaloneQuery", query);
        plan.put("reads", List.of());
        plan.put("steps", List.of());
        plan.put("operation", "NONE");
        plan.put("target", "selected");
        plan.put("count", 5);
        plan.put("conditionPatch", Map.of());
        if (AdmissionLinksValidator.compound(query)) {
            plan.put("clarification", AdmissionLinksValidator.SPLIT);
        } else if (names.size() != 1) {
            plan.put("clarification", names.isEmpty() ? "请提供一个院校全名。" : "本轮包含多所院校，请只选择一所。");
        } else if (years.size() > 1 || majors.size() > 1) {
            plan.put("clarification", "请指定一个招生年份和一个专业代码，或省略这些筛选条件。");
        } else {
            Map<String, Object> lookup = new LinkedHashMap<>();
            lookup.put("schoolName", names.iterator().next());
            lookup.put("year", years.isEmpty() ? null : Integer.valueOf(years.iterator().next()));
            lookup.put("majorCode", majors.isEmpty() ? null : majors.iterator().next());
            plan.put("schoolLookup", lookup);
        }
        return plan;
    }

    private static Set<String> matches(String text, String pattern, int group) {
        Set<String> values = new LinkedHashSet<>();
        var matcher = Pattern.compile(pattern).matcher(text);
        while (matcher.find()) values.add(matcher.group(group));
        return values;
    }

    /** Independently verify upstream plans against the actual current user text. */
    public static void validatePlan(Map<String, Object> plan, String query) {
        if (!"SCHOOL_LOOKUP".equals(plan.get("action"))) {
            if (plan.get("schoolLookup") != null) throw new IllegalStateException("unexpected_school_lookup");
            return;
        }
        var expected = plan(query);
        if (expected == null || !Objects.equals(expected.get("schoolLookup"), plan.get("schoolLookup"))
                || !Objects.equals(expected.get("clarification"), plan.get("clarification"))
                || !"NONE".equals(plan.get("operation"))
                || !(plan.get("reads") instanceof List<?> reads) || !reads.isEmpty()
                || (plan.get("steps") instanceof List<?> steps && !steps.isEmpty()))
            throw new IllegalStateException("school_lookup_intent_mismatch");
    }

    /** Build the immutable response snapshot using only whitelisted public fields. */
    public Map<String, Object> answer(Map<String, Object> plan, Map<String, Object> profile,
                                      Map<String, Object> conditions) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("resolvedTaskType", "CHAT");
        result.put("releaseId", RELEASE);
        result.put("explanationMode", "rules");
        result.put("references", List.of());
        result.put("conditions", conditions);
        result.put("dataScopes", List.of());
        result.put("readScope", List.of());
        result.put("standaloneQuery", plan.get("standaloneQuery"));
        if (plan.get("clarification") != null) {
            result.put("outcome", "NEEDS_INPUT");
            result.put("answer", plan.get("clarification"));
            return result;
        }
        @SuppressWarnings("unchecked")
        var lookup = (Map<String, Object>) plan.get("schoolLookup");
        String name = lookup.get("schoolName").toString();
        var links = AdmissionLinksValidator.linksForName(name);
        if (links != null) result.put("admissionLinks", links);
        List<School> found = schools.lambdaQuery().eq(School::getName, name).list();
        if (found.size() != 1) {
            Map<String, Object> empty = new LinkedHashMap<>();
            empty.put("school", null);
            empty.put("targetYear", lookup.get("year"));
            empty.put("availableYears", List.of());
            empty.put("details", List.of());
            empty.put("total", 0);
            empty.put("warnings", List.of());
            result.put("schoolCatalog", empty);
            result.put("outcome", found.size() > 1 ? "NEEDS_INPUT" : "UNSUPPORTED");
            result.put("answer", found.isEmpty() ? "院校库尚未收录“" + name + "”的信息。"
                    : "院校库存在同名记录，请联系维护者核对招生主体。");
            if (links == null) result.put("notice", "该院校未登记官网确认链接，请通过院校官方渠道确认。");
            return result;
        }
        School school = found.get(0);
        var detail = schools.detail(school.getId());
        @SuppressWarnings("unchecked")
        List<SchoolDetail> all = (List<SchoolDetail>) detail.get("details");
        List<Integer> years = all.stream().map(SchoolDetail::getYear).filter(Objects::nonNull)
                .distinct().sorted(Comparator.reverseOrder()).toList();
        Integer year = lookup.get("year") instanceof Number value ? value.intValue() : null;
        if (year == null && profile.get("examYear") instanceof Number value) {
            year = value.intValue();
            result.put("dataScopes", List.of("profile"));
        }
        if (year == null && !years.isEmpty()) year = years.get(0);
        final Integer targetYear = year;
        var matching = all.stream().filter(row -> targetYear == null || targetYear.equals(row.getYear()))
                .filter(row -> lookup.get("majorCode") == null || lookup.get("majorCode").equals(row.getMajorCode()))
                .sorted(Comparator.comparing(SchoolDetail::getYear, Comparator.nullsLast(Comparator.reverseOrder()))
                        .thenComparing(SchoolDetail::getMajorCode, Comparator.nullsLast(Comparator.naturalOrder()))
                        .thenComparing(SchoolDetail::getId)).toList();
        Map<String, Object> catalog = new LinkedHashMap<>();
        Map<String, Object> basic = new LinkedHashMap<>();
        basic.put("id", school.getId()); basic.put("name", school.getName());
        basic.put("province", school.getProvince()); basic.put("level", school.getLevel());
        catalog.put("school", basic);
        catalog.put("targetYear", year);
        catalog.put("availableYears", years);
        catalog.put("details", matching.stream().limit(10).map(SchoolCatalogService::publicDetail).toList());
        catalog.put("total", matching.size());
        Set<Long> visible = matching.stream().limit(10).map(SchoolDetail::getId).collect(java.util.stream.Collectors.toSet());
        var warnings = detail.get("warnings") instanceof List<?> list ? list.stream()
                .filter(item -> item instanceof com.kaoyan.dto.response.SchoolWarning warning
                        && (warning.detailId() == null || visible.contains(warning.detailId()))).toList() : List.of();
        catalog.put("warnings", warnings);
        String query = Objects.toString(plan.get("standaloneQuery"), "");
        boolean scoreQuestion = scoreRequested(query);
        String detailsText = matching.isEmpty()
                ? "已找到" + name + "，但库内没有符合本次年份及专业条件的招生记录；未替换为其他年份。"
                : "已找到" + name + "库内" + (year == null ? "" : year + "年") + matching.size()
                    + "条专业记录，以下展示前" + Math.min(10, matching.size()) + "条。已有资料及待核实状态如下。";
        String scoreText;
        if (detail.get("scoreStatistics") instanceof List<?> stored) {
            @SuppressWarnings("unchecked")
            var scores = filterScores((List<ScoreStatisticVO>) stored, lookup, query);
            Map<String, Object> block = new LinkedHashMap<>();
            block.put("total", scores.size());
            block.put("notice", SchoolScoreStatistics.NOTICE);
            block.put("items", scores.stream().limit(SCORE_LIMIT).toList());
            catalog.put("scoreStatistics", block);
            scoreText = scores.isEmpty()
                    ? name + "暂无符合本次条件的往年录取分数统计。"
                    : "收录" + name + "往年录取分数统计" + scores.size() + "条，展示前"
                        + Math.min(SCORE_LIMIT, scores.size()) + "条。" + SchoolScoreStatistics.NOTICE;
        } else {
            scoreText = scoreQuestion ? "院校库暂未提供录取分数统计。" : null;
        }
        result.put("schoolCatalog", catalog);
        result.put("outcome", "COMPLETED");
        result.put("answer", scoreText == null ? detailsText
                : scoreQuestion ? scoreText + "\n" + detailsText : detailsText + "\n" + scoreText);
        if (links == null) result.put("notice", "该院校未登记官网确认链接，请通过院校官方渠道确认。");
        return result;
    }

    /** Explicit year and code filter exactly; otherwise major names named in the question narrow the list. */
    static List<ScoreStatisticVO> filterScores(List<ScoreStatisticVO> rows, Map<String, Object> lookup, String query) {
        Integer year = lookup.get("year") instanceof Number value ? value.intValue() : null;
        Object code = lookup.get("majorCode");
        var scoped = rows.stream().filter(row -> year == null || year.equals(row.year()))
                .filter(row -> code == null || code.equals(row.majorCode())).toList();
        if (code != null) return scoped;
        Set<String> named = new LinkedHashSet<>();
        for (ScoreStatisticVO row : scoped) {
            String core = majorCore(row.majorName());
            if (core.length() >= 2 && query.contains(core)) named.add(core);
        }
        return named.isEmpty() ? scoped
                : scoped.stream().filter(row -> named.contains(majorCore(row.majorName()))).toList();
    }

    /** Major name without bracketed qualifiers or spaces, e.g. 计算机技术（非全） to 计算机技术. */
    public static String majorCore(String major) {
        return major == null ? "" : major.replaceAll("[（(][^）)]*[）)]?", "").replaceAll("\\s+", "");
    }

    private static Map<String, Object> publicDetail(SchoolDetail row) {
        Map<String, Object> value = new LinkedHashMap<>();
        value.put("id", row.getId()); value.put("schoolId", row.getSchoolId());
        value.put("majorName", row.getMajorName()); value.put("majorCode", row.getMajorCode());
        value.put("year", row.getYear()); value.put("remark", row.getRemark());
        value.put("enrollmentCount", row.getEnrollmentCount()); value.put("scoreLine", row.getScoreLine());
        if (row.getAdmissionMetrics() != null) value.put("admissionMetrics", row.getAdmissionMetrics());
        return value;
    }
}
