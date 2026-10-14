package com.example.slowquery.mapper;

import com.example.slowquery.model.Article;
import com.example.slowquery.model.Author;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

@Mapper
public interface ArticleMapper {

    @Select(
        "SELECT * FROM articles " +
        "ORDER BY created_at DESC " +
        "LIMIT #{size}"
    )
    List<Article> findRecentArticles(@Param("size") int size);

    @Select(
        "SELECT id, name, email, created_at FROM authors " +
        "WHERE id = #{id}"
    )
    Author findAuthorById(@Param("id") Long id);
}
