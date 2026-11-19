package com.kaoyan;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.system.CapturedOutput;
import org.springframework.boot.test.system.OutputCaptureExtension;
import org.springframework.context.annotation.Import;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.ResultActions;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;
import java.util.UUID;

import static org.hamcrest.Matchers.containsString;
import static org.hamcrest.Matchers.not;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * 全局异常处理的 HTTP 状态码与统一响应体：Spring MVC 标准异常保留各自状态码，
 * 未知异常仍为 500；需要认证的路径未登录时先由安全链返回 401。
 */
@SpringBootTest(properties = {
    "spring.datasource.driver-class-name=org.h2.Driver",
    "spring.datasource.url=jdbc:h2:mem:global_exception_status;MODE=MySQL;DB_CLOSE_DELAY=-1;NON_KEYWORDS=USER",
    "spring.datasource.username=sa", "spring.datasource.password=",
    "spring.sql.init.mode=always", "spring.sql.init.schema-locations=classpath:schema-test.sql",
    "jwt.secret=test-only-jwt-key-at-least-32-characters",
    "kaoyan.agent.internal-key=test-only-internal-key-12345",
    "springdoc.api-docs.enabled=false"
})
@AutoConfigureMockMvc
@Import(GlobalExceptionStatusTest.FailingController.class)
@ExtendWith(OutputCaptureExtension.class)
class GlobalExceptionStatusTest {

    /** 仅测试上下文注册：模拟业务代码抛出的未知异常。 */
    @RestController
    static class FailingController {
        @GetMapping("/api/test-only/boom")
        String boom() {
            throw new IllegalStateException("secret-sql-param=private-text");
        }
    }

    @Autowired MockMvc mvc;
    @Autowired ObjectMapper json;
    @MockitoBean StringRedisTemplate redis;

    private String login() throws Exception {
        String body = json.writeValueAsString(Map.of(
                "username", "ge_" + UUID.randomUUID().toString().substring(0, 8), "password", "synthetic-pass"));
        mvc.perform(post("/api/auth/register").contentType("application/json").content(body)).andExpect(status().isOk());
        return json.readTree(mvc.perform(post("/api/auth/login").contentType("application/json").content(body))
                .andExpect(status().isOk()).andReturn().getResponse().getContentAsString())
                .path("data").path("accessToken").asText();
    }

    private static void expectFail(ResultActions result, int status) throws Exception {
        result.andExpect(status().is(status))
                .andExpect(jsonPath("$.code").value(status))
                .andExpect(jsonPath("$.message").isString())
                .andExpect(jsonPath("$.data").doesNotExist());
    }

    @Test void unauthenticatedProtectedPathsStay401BeforeRouting() throws Exception {
        expectFail(mvc.perform(get("/api/no-such-path")), 401);
        expectFail(mvc.perform(get("/api/exports/abc/file")), 401);
        expectFail(mvc.perform(delete("/api/users/me")), 401);
        expectFail(mvc.perform(get("/api/test-only/boom")), 401);
    }

    @Test void missingResourcesReturn404WithoutErrorLog(CapturedOutput output) throws Exception {
        String token = login();
        expectFail(mvc.perform(get("/v3/api-docs")), 404);
        expectFail(mvc.perform(get("/api/auth/no-such-path")), 404);
        expectFail(mvc.perform(get("/api/no-such-path").header("Authorization", "Bearer " + token)), 404);
        mvc.perform(get("/v3/api-docs")).andExpect(jsonPath("$.message", not(containsString("api-docs"))));
        assertFalse(output.getAll().contains("未处理异常"), "标准 404 不应记录为未处理异常");
    }

    @Test void unsupportedMethodReturns405WithAllowHeader() throws Exception {
        expectFail(mvc.perform(get("/api/auth/login")), 405);
        mvc.perform(get("/api/auth/login")).andExpect(header().string("Allow", containsString("POST")));
        String token = login();
        expectFail(mvc.perform(delete("/api/users/me").header("Authorization", "Bearer " + token)), 405);
    }

    @Test void unsupportedMediaTypeReturns415() throws Exception {
        expectFail(mvc.perform(post("/api/auth/login").contentType("text/plain").content("x")), 415);
    }

    @Test void missingOrMismatchedParametersReturn400() throws Exception {
        String token = login();
        expectFail(mvc.perform(get("/api/exports/abc/file").header("Authorization", "Bearer " + token)), 400);
        mvc.perform(get("/api/exports/abc/file").header("Authorization", "Bearer " + token))
                .andExpect(jsonPath("$.message", not(containsString("format"))));
        expectFail(mvc.perform(get("/api/questions/not-a-number").header("Authorization", "Bearer " + token)), 400);
    }

    @Test void unknownExceptionStays500WithoutLeakingDetails(CapturedOutput output) throws Exception {
        String token = login();
        expectFail(mvc.perform(get("/api/test-only/boom").header("Authorization", "Bearer " + token)), 500);
        mvc.perform(get("/api/test-only/boom").header("Authorization", "Bearer " + token))
                .andExpect(jsonPath("$.message").value("服务器内部错误"));
        assertFalse(output.getAll().contains("private-text"), "日志与响应不应包含异常消息");
    }
}
