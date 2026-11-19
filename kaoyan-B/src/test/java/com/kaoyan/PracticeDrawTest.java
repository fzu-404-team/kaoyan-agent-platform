package com.kaoyan;

import com.kaoyan.entity.Question;
import com.kaoyan.service.PracticeDraw;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;

class PracticeDrawTest {
    @Test void batchLoadRetainsSelectedOrderAndSkipsMissingQuestions() {
        Question first = new Question();
        first.setId(1L);
        Question third = new Question();
        third.setId(3L);
        assertEquals(List.of(third, first), PracticeDraw.inSelectionOrder(List.of(3L, 2L, 1L), List.of(first, third)));
    }
}
