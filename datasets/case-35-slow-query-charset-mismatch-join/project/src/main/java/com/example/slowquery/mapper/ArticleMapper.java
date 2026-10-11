package com.example.slowquery.mapper;

import com.example.slowquery.dto.ArticleVO;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

@Mapper
public interface ArticleMapper {

    @Select(
        "SELECT a.id, a.article_code, a.title, au.name " +
        "FROM authors au " +
        "JOIN articles a ON a.author_code = au.author_code " +
        "WHERE au.author_code = #{authorCode}"
    )
    List<ArticleVO> findByAuthorCode(@Param("authorCode") String authorCode);
}
