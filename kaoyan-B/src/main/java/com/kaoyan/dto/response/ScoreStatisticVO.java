package com.kaoyan.dto.response;

import java.util.List;

/** User-provided, user-approved admission score statistics; never official data or recommendation evidence. */
public record ScoreStatisticVO(
        Long id, Integer year, String college, String majorCode, String majorName, String examCombo,
        Double retestLine, Double minScore, Double medianScore, Double avgScore, Double maxScore,
        Integer admittedCount, List<String> flags) {
}
