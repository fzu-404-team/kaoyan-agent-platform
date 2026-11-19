package com.kaoyan.common;

import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.http.HttpStatusCode;
import org.springframework.http.ResponseEntity;
import org.springframework.validation.BindException;
import org.springframework.web.ErrorResponse;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

/**
 * 全局异常处理
 */
@Slf4j
@RestControllerAdvice
public class GlobalExceptionHandler {

    @ExceptionHandler(ApiException.class)
    public ResponseEntity<Result<Void>> handleApi(ApiException e) {
        return ResponseEntity.status(e.getHttpStatus())
                .body(Result.fail(e.getCode(), e.getMessage()));
    }

    @ExceptionHandler({MethodArgumentNotValidException.class, BindException.class})
    public ResponseEntity<Result<Void>> handleValid(BindException e) {
        String msg = e.getBindingResult().getAllErrors().isEmpty()
                ? "参数校验失败"
                : e.getBindingResult().getAllErrors().get(0).getDefaultMessage();
        return ResponseEntity.status(400).body(Result.fail(400, msg));
    }

    @ExceptionHandler({org.springframework.http.converter.HttpMessageNotReadableException.class,
            org.springframework.web.method.annotation.MethodArgumentTypeMismatchException.class})
    public ResponseEntity<Result<Void>> handleFormat(Exception e) {
        return ResponseEntity.badRequest().body(Result.fail(400, "输入格式不正确"));
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<Result<Void>> handleOther(Exception e) {
        if (e instanceof ErrorResponse errorResponse) {
            return handleFrameworkError(e, errorResponse);
        }
        // Exception messages/stacks can contain SQL parameters and private document text.
        log.error("未处理异常 type={}", e.getClass().getSimpleName());
        return ResponseEntity.status(500).body(Result.fail(500, "服务器内部错误"));
    }

    /**
     * Spring MVC 标准异常（NoResourceFoundException、HttpRequestMethodNotSupportedException、
     * HttpMediaTypeNotSupportedException、MissingServletRequestParameterException 等）已经通过
     * {@link ErrorResponse} 声明了正确的状态码和响应头（如 405 的 Allow），这里统一沿用，
     * 只替换为固定安全提示：其 detail 可能包含路径、参数名或类型名，不对外返回。
     */
    private ResponseEntity<Result<Void>> handleFrameworkError(Exception e, ErrorResponse errorResponse) {
        HttpStatusCode status = errorResponse.getStatusCode();
        if (status.is5xxServerError()) {
            log.warn("框架异常 status={} type={}", status.value(), e.getClass().getSimpleName());
        } else {
            log.debug("请求无法处理 status={} type={}", status.value(), e.getClass().getSimpleName());
        }
        return ResponseEntity.status(status)
                .headers(errorResponse.getHeaders())
                .body(Result.fail(status.value(), safeMessage(status)));
    }

    private static String safeMessage(HttpStatusCode status) {
        HttpStatus known = HttpStatus.resolve(status.value());
        if (known == null) {
            return status.is4xxClientError() ? "请求无法处理" : "服务器内部错误";
        }
        return switch (known) {
            case BAD_REQUEST -> "请求参数不正确";
            case NOT_FOUND -> "请求的资源不存在";
            case METHOD_NOT_ALLOWED -> "不支持的请求方法";
            case NOT_ACCEPTABLE -> "不支持的响应格式";
            case PAYLOAD_TOO_LARGE -> "请求内容过大";
            case UNSUPPORTED_MEDIA_TYPE -> "不支持的请求内容类型";
            case SERVICE_UNAVAILABLE -> "服务暂不可用";
            default -> known.is4xxClientError() ? "请求无法处理" : "服务器内部错误";
        };
    }
}
