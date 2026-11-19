package com.kaoyan.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.kaoyan.entity.Question;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

/**
 * 题库 Mapper
 */
@Mapper
public interface QuestionMapper extends BaseMapper<Question> {

    @Select("SELECT * FROM question WHERE id = #{id} FOR UPDATE")
    Question selectForUpdate(@Param("id") Long id);

    /**
     * 按条件抽题用于刷题：active=1 且已审核
     *
     * @param subject       科目（可空）
     * @param difficulty    难度（可空）
     * @param knowledgePoint 知识点（可空）
     * @param limit         抽取数量
     * @return 题目列表
     */
    @Select("<script>" +
            "SELECT * FROM question WHERE active = 1 AND review_status = 'APPROVED'" +
            "<if test='subject != null and subject != \"\"'> AND subject = #{subject}</if>" +
            "<if test='difficulty != null and difficulty != \"\"'> AND difficulty = #{difficulty}</if>" +
            "<if test='knowledgePoint != null and knowledgePoint != \"\"'> AND knowledge_point LIKE CONCAT('%', #{knowledgePoint}, '%')</if>" +
            " ORDER BY stable_order LIMIT #{limit}" +
            "</script>")
    List<Question> selectForPractice(@Param("subject") String subject,
                                     @Param("difficulty") String difficulty,
                                     @Param("knowledgePoint") String knowledgePoint,
                                     @Param("limit") int limit);

    /** 按本人最近有效作答排序抽取题号，未作答优先且同一时间随机。 */
    @Select("""
        <script>
        SELECT q.id
        FROM question q
        LEFT JOIN (
            SELECT question_id, MAX(answered_at) AS last_answered_at
            FROM practice_record
            WHERE user_id = #{userId} AND grading_status = 'valid' AND answered_at IS NOT NULL
            GROUP BY question_id
        ) seen ON seen.question_id = q.id
        WHERE q.active = 1 AND q.review_status = 'APPROVED'
        <!-- Marked draws used Java exact equality. REPLACE matches case-sensitively in MySQL and H2. -->
        <if test='subject != null and subject != ""'>
            AND q.subject = #{subject}
            <if test='source != "NORMAL"'>
                AND OCTET_LENGTH(q.subject) = OCTET_LENGTH(#{subject})
                AND OCTET_LENGTH(REPLACE(q.subject, #{subject}, '')) = 0
            </if>
        </if>
        <if test='difficulty != null and difficulty != ""'>
            AND q.difficulty = #{difficulty}
            <if test='source != "NORMAL"'>
                AND OCTET_LENGTH(q.difficulty) = OCTET_LENGTH(#{difficulty})
                AND OCTET_LENGTH(REPLACE(q.difficulty, #{difficulty}, '')) = 0
            </if>
        </if>
        <if test='source != "NORMAL"'>
            AND EXISTS (
                SELECT 1 FROM user_question_mark m
                WHERE m.user_id = #{userId} AND m.question_id = q.id
                <choose>
                    <when test='source == "WRONG"'>AND m.is_wrong = 1</when>
                    <otherwise>AND m.is_favorite = 1</otherwise>
                </choose>
            )
        </if>
        ORDER BY CASE WHEN seen.last_answered_at IS NULL THEN 0 ELSE 1 END,
                 seen.last_answered_at, RAND()
        LIMIT #{limit}
        </script>
        """)
    List<Long> drawPracticeIds(@Param("userId") Long userId, @Param("source") String source,
                               @Param("subject") String subject, @Param("difficulty") String difficulty,
                               @Param("limit") int limit);
}
