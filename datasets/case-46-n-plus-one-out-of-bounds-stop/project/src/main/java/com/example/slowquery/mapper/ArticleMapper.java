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

    // 该子查询的 SQL 定义在 XML mapper（resources/mapper/ArticleMapper.xml）中，
    // 而非 @Select 注解；接口方法仅保留签名。
    Author findAuthorById(@Param("id") Long id);
}
