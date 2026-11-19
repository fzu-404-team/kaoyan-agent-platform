package com.kaoyan.service;

import com.kaoyan.entity.Question;

import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.function.Function;
import java.util.stream.Collectors;

/** 刷题批次的题序在创建时固定。 */
public final class PracticeDraw {

    private PracticeDraw() {
    }

    /** 按已选题号还原批量查询的题序；查询不到的题目无法加入批次。 */
    public static List<Question> inSelectionOrder(List<Long> selectedIds, List<Question> loaded) {
        Map<Long, Question> byId = loaded.stream().collect(Collectors.toMap(Question::getId, Function.identity()));
        return selectedIds.stream().map(byId::get).filter(Objects::nonNull).toList();
    }
}
