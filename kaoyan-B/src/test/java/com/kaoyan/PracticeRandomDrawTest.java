package com.kaoyan;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.kaoyan.entity.Question;
import com.kaoyan.feign.AgentFeignClient;
import com.kaoyan.mapper.QuestionMapper;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.context.bean.override.mockito.MockitoSpyBean;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.clearInvocations;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/** 2026-11-19 随机抽题：经真实接口与 H2 持久化验证。 */
@SpringBootTest(properties = {
    "spring.datasource.driver-class-name=org.h2.Driver",
    "spring.datasource.url=jdbc:h2:mem:random-draw;MODE=MySQL;DB_CLOSE_DELAY=-1;NON_KEYWORDS=USER",
    "spring.datasource.username=sa", "spring.datasource.password=",
    "spring.sql.init.mode=always", "spring.sql.init.schema-locations=classpath:schema-test.sql,classpath:schema-practice.sql",
    "jwt.secret=test-only-jwt-key-at-least-32-characters",
    "kaoyan.agent.internal-key=test-only-internal-key-12345", "oss.endpoint=", "oss.access-key-id="
})
@AutoConfigureMockMvc
class PracticeRandomDrawTest {
    @Autowired MockMvc mvc;
    @Autowired ObjectMapper json;
    @MockitoSpyBean QuestionMapper questions;
    @Autowired JdbcTemplate jdbc;
    @MockitoBean AgentFeignClient agent;
    @MockitoBean StringRedisTemplate redis;

    JsonNode call(MockHttpServletRequestBuilder req, String token, Object body, int code) throws Exception {
        if (token != null) req.header("Authorization", "Bearer " + token);
        if (body != null) req.contentType("application/json").content(json.writeValueAsString(body));
        String text = mvc.perform(req).andExpect(status().is(code)).andReturn().getResponse().getContentAsString();
        return text.isBlank() ? json.nullNode() : json.readTree(text).path("data");
    }

    String login() throws Exception {
        return login("s" + UUID.randomUUID().toString().replace("-", "").substring(0, 15));
    }

    String login(String username) throws Exception {
        var body = Map.of("username", username, "password", "test-password");
        call(post("/api/auth/register"), null, body, 200);
        return call(post("/api/auth/login"), null, body, 200).path("accessToken").asText();
    }

    /** Six approved questions in a fresh subject; stable_order runs opposite to id. */
    List<Question> bank(String subject) {
        var out = new ArrayList<Question>();
        for (int i = 0; i < 6; i++) {
            var q = new Question(); q.setSubject(subject); q.setKnowledgePoint("抽题测试");
            q.setContent("题干" + i); q.setOptionA("A"); q.setOptionB("B"); q.setOptionC("C"); q.setOptionD("D");
            q.setAnswer("A"); q.setAnalysis("解析"); q.setActive(1); q.setVersion(1); q.setDifficulty("EASY");
            q.setReviewStatus("APPROVED"); q.setQuestionType("SINGLE_CHOICE"); q.setStableOrder(10 - i);
            questions.insert(q); out.add(q);
        }
        return out;
    }

    List<Long> start(String token, Map<String, Object> body) throws Exception {
        String session = call(post("/api/practice/sessions"), token, body, 200).path("sessionId").asText();
        var ids = new ArrayList<Long>();
        call(get("/api/practice/sessions/" + session), token, null, 200).forEach(r -> ids.add(r.path("questionId").asLong()));
        return ids;
    }

    String answerAll(String token, Map<String, Object> body, String option) throws Exception {
        String session = call(post("/api/practice/sessions"), token, body, 200).path("sessionId").asText();
        for (JsonNode r : call(get("/api/practice/sessions/" + session), token, null, 200))
            call(post("/api/practice/sessions/" + session + "/answer"), token, Map.of("questionId", r.path("questionId").asLong(), "answer", option), 200);
        return session;
    }

    @Test void unseenFirstThenOldestAnsweredAndAccountsAreIsolated() throws Exception {
        String subject = "s" + UUID.randomUUID().toString().substring(0, 8);
        var bank = bank(subject);
        String token = login();
        var body = new LinkedHashMap<String, Object>(Map.of("subject", subject, "count", 3));
        String first = answerAll(token, body, "A");
        var firstIds = new HashSet<Long>(jdbc.queryForList("SELECT question_id FROM practice_record WHERE session_id=?", Long.class, first));
        // The next batch draws only questions this account has never answered.
        var second = start(token, body);
        assertEquals(3, second.size());
        assertTrue(second.stream().noneMatch(firstIds::contains));
        // After all six are answered, the oldest answered questions come back first.
        String secondSession = answerAll(token, body, "A");
        var oldest = firstIds.stream().sorted().toList();
        for (int i = 0; i < oldest.size(); i++) {
            jdbc.update("UPDATE practice_record SET answered_at=? WHERE session_id=? AND question_id=?",
                    java.time.LocalDateTime.of(2026, 1, 1, 8, i), first, oldest.get(i));
        }
        jdbc.update("UPDATE practice_record SET answered_at=TIMESTAMP '2026-02-01 08:00:00' WHERE session_id=?", secondSession);
        assertEquals(oldest, start(token, body));
        body.put("count", 6);
        Set<List<Long>> tieOrders = new HashSet<>();
        for (int i = 0; i < 8; i++) {
            var draw = start(token, body);
            assertEquals(6, new HashSet<>(draw).size());
            assertEquals(oldest, draw.subList(0, 3));
            tieOrders.add(draw.subList(3, 6));
        }
        assertTrue(tieOrders.size() > 1, "questions with the same answer time are ordered randomly");
        // Another account has answered nothing, so it may draw any of the six.
        String other = login();
        assertEquals(6, start(other, Map.of("subject", subject, "count", 6)).size());
        // The stable-order question endpoint is unchanged.
        var listed = new ArrayList<Long>();
        call(get("/api/questions/practice").param("subject", subject).param("limit", "6"), token, null, 200)
            .forEach(q -> listed.add(q.path("id").asLong()));
        var expected = new ArrayList<Long>(bank.stream().map(Question::getId).toList());
        java.util.Collections.reverse(expected);
        assertEquals(expected, listed);
    }

    @Test void freshBatchesVaryAndWrongBookDrawsOnlyOwnQuestions() throws Exception {
        String subject = "s" + UUID.randomUUID().toString().substring(0, 8);
        bank(subject);
        Set<Set<Long>> draws = new HashSet<>();
        for (int i = 0; i < 8; i++) draws.add(new HashSet<>(start(login(), Map.of("subject", subject, "count", 3))));
        assertTrue(draws.size() > 1, "eight fresh accounts should not all draw the same three questions");
        String token = login();
        String wrongSession = answerAll(token, Map.of("subject", subject, "count", 2), "B");
        var wrong = new HashSet<Long>(jdbc.queryForList("SELECT question_id FROM practice_record WHERE session_id=?", Long.class, wrongSession));
        var drawn = start(token, Map.of("subject", subject, "count", 5, "source", "WRONG"));
        assertEquals(wrong, new HashSet<>(drawn));
    }

    @Test void favoriteDrawDoesNotLoadEachMarkedQuestion() throws Exception {
        String subject = "s" + UUID.randomUUID().toString().substring(0, 8);
        var bank = bank(subject);
        String token = login(subject);
        var owner = jdbc.queryForObject("SELECT id FROM `user` WHERE username=?", Long.class, subject);
        for (Question q : bank.subList(0, 4)) {
            jdbc.update("INSERT INTO user_question_mark(user_id,question_id,is_favorite) VALUES(?,?,1)", owner, q.getId());
        }
        jdbc.update("INSERT INTO user_question_mark(user_id,question_id,is_favorite) VALUES(?,?,1)", owner + 1, bank.get(4).getId());
        jdbc.update("UPDATE question SET active=0 WHERE id=?", bank.get(3).getId());
        assertEquals(new HashSet<>(bank.subList(0, 3).stream().map(Question::getId).toList()),
                new HashSet<>(start(token, Map.of("subject", subject, "count", 6, "source", "FAVORITE"))));
        clearInvocations(questions);
        var result = call(post("/api/practice/sessions"), token,
                Map.of("subject", subject, "difficulty", "EASY", "count", 2, "source", "FAVORITE"), 200);
        var drawn = jdbc.queryForList("SELECT question_id FROM practice_record WHERE session_id=? ORDER BY order_index",
                Long.class, result.path("sessionId").asText());
        assertEquals(2, new HashSet<>(drawn).size());
        assertTrue(bank.subList(0, 3).stream().map(Question::getId).toList().containsAll(drawn));
        verify(questions, never()).selectById(any());

        var explicit = List.of(bank.get(2).getId(), bank.get(0).getId());
        assertEquals(explicit, start(token, Map.of("count", 6, "source", "FAVORITE", "questionIds", explicit)));
        call(post("/api/practice/sessions"), token,
                Map.of("subject", subject, "difficulty", "easy", "count", 1, "source", "FAVORITE"), 404);
        call(post("/api/practice/sessions"), token,
                Map.of("count", 2, "source", "FAVORITE", "questionIds", List.of(bank.get(4).getId())), 404);
    }
}
