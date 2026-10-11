package com.example.slowquery.mapper;

import com.example.slowquery.model.Commit;
import com.example.slowquery.model.Repository;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;

@Mapper
public interface RepositoryMapper {

    @Select("SELECT id, owner, name, created_at_ms FROM repositories ORDER BY created_at_ms DESC LIMIT #{size}")
    List<Repository> findRecentRepositories(@Param("size") int size);

    @Select("SELECT id, repository_id, committer_id, message FROM commits WHERE repository_id = #{repositoryId}")
    List<Commit> findCommitsByRepositoryId(@Param("repositoryId") long repositoryId);

    @Select("SELECT name FROM committers WHERE id = #{committerId}")
    String findCommitterNameById(@Param("committerId") long committerId);
}
