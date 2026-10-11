package com.example.slowquery.mapper;

import com.example.slowquery.model.Article;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

@Mapper
public interface ArticleMapper {

    @Select(
        "SELECT * " +
        "FROM articles " +
        "WHERE title LIKE CONCAT('%', #{keyword}, '%') " +
        "ORDER BY published_at_ms DESC " +
        "LIMIT #{limit}"
    )
    List<Article> searchByTitle(@Param("keyword") String keyword, @Param("limit") int limit);
}
